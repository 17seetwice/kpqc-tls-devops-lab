#define _DEFAULT_SOURCE
#define _POSIX_C_SOURCE 200809L
#include <openssl/ssl.h>
#include <openssl/err.h>
#include <openssl/provider.h>
#include <arpa/inet.h>
#include <netinet/tcp.h>
#include <sys/socket.h>
#include <sys/resource.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <fcntl.h>
#include <sys/mman.h>
#include <string.h>
#include <errno.h>

/* Timing boundary: ONE blocking SSL_connect/SSL_accept call, after all setup.
 * A one-byte plaintext readiness preface precedes TLS and is excluded from
 * timing. It prevents server process/provider setup from entering client time.
 * This is an instrumented benchmark endpoint, not an HTTP production server.
 */
/* 실제 TLS 메시지에서 관찰한 KEM 그룹·CertificateVerify 서명 코드와 HRR 횟수를 저장한다.
 * 인증서의 공개키 종류만 보는 것이 아니라 협상에 사용된 알고리즘을 확인하기 위한 증적이다.
 */
struct trace { unsigned group, signature, hrr, messages; size_t sent_bytes, received_bytes; };
/* TLS 메시지의 2바이트 정수를 네트워크 바이트 순서(상위 바이트 먼저)로 읽는다.
 */
static unsigned u16(const unsigned char *p) { return ((unsigned)p[0]<<8)|p[1]; }
/* OpenSSL의 메시지 콜백이다. TLS 레코드 전체가 아닌 핸드셰이크 메시지만 분석한다.
 */
static void msg(int out, int version, int type, const void *v, size_t n, SSL *s, void *arg) {
    (void)out;(void)version;(void)s;
    struct trace *t=arg; const unsigned char *p=v;
    if(type!=SSL3_RT_HANDSHAKE || n<4)return;
    t->messages++;
    if(out)t->sent_bytes+=n;else t->received_bytes+=n;
    /* CertificateVerify의 서명 알고리즘 필드다. 현재 시험은 서버 인증만 하며 mTLS 시험은 아니다.
     */
    if(p[0]==SSL3_MT_CERTIFICATE_VERIFY && n>=6)t->signature=u16(p+4);
    if(p[0]!=SSL3_MT_SERVER_HELLO || n<39)return;
    /* HelloRetryRequest는 특별한 ServerHello random 값으로 구별한다. 추가 왕복 발생 여부를 기록한다.
     */
    static const unsigned char hrr[32]={0xcf,0x21,0xad,0x74,0xe5,0x9a,0x61,0x11,0xbe,0x1d,0x8c,0x02,0x1e,0x65,0xb8,0x91,0xc2,0xa2,0x11,0x16,0x7a,0xbb,0x8c,0x5e,0x07,0x9e,0x09,0xe2,0xc8,0xa8,0x33,0x9c};
    if(!memcmp(p+6,hrr,32))t->hrr++;
    size_t x=39+p[38]; /* session id, cipher suite, compression, extensions */
    if(x+5>n)return;
    x+=3; size_t end=x+2+u16(p+x); x+=2;
    if(end>n)return;
    while(x+4<=end){unsigned ty=u16(p+x),len=u16(p+x+2);x+=4;
        if(x+len>end)return;
        /* 확장 51은 key_share다. 서버가 선택한 그룹 코드를 기록하며, 사용자 이미지의 커스텀 코드도 그대로 관찰한다.
         */
        if(ty==51 && len>=2)t->group=u16(p+x);
        x+=len;
    }
}
static void die(const char *s){perror(s);ERR_print_errors_fp(stderr);exit(2);}
static double tvms(struct timeval t){return t.tv_sec*1000.0+t.tv_usec/1000.0;}
static double diff(struct timespec a,struct timespec b){return(b.tv_sec-a.tv_sec)*1000.0+(b.tv_nsec-a.tv_nsec)/1e6;}
/* Provider와 TLS 설정·인증서를 준비한다. 이 초기화 구간은 아래 핸드셰이크 타이머 밖에 있다.
 */
static SSL_CTX *context(int server,const char *group,const char *sig,const char *cert,const char *key){
    if(!OSSL_PROVIDER_load(NULL,"default")||!OSSL_PROVIDER_load(NULL,"oqsprovider"))die("provider");
    SSL_CTX *c=SSL_CTX_new(server?TLS_server_method():TLS_client_method());if(!c)die("context");
    if(!SSL_CTX_set_min_proto_version(c,(getenv("KPQC_TLS12")?TLS1_2_VERSION:TLS1_3_VERSION))||!SSL_CTX_set_max_proto_version(c,(getenv("KPQC_TLS12")?TLS1_2_VERSION:TLS1_3_VERSION))
       ||!SSL_CTX_set_ciphersuites(c,"TLS_AES_256_GCM_SHA384")||!SSL_CTX_set1_groups_list(c,getenv("KPQC_TLS12")?"X25519:P-256":group)
       ||!SSL_CTX_set1_sigalgs_list(c,sig))die("TLS configuration");
    if(getenv("KPQC_TLS12") && !SSL_CTX_set_cipher_list(c,"ECDHE-ECDSA-AES256-GCM-SHA384"))die("TLS 1.2 cipher");
    /* 매번 완전한 핸드셰이크를 비교하기 위해 세션 캐시·티켓 사용을 끈다. 결과의 reused도 별도로 확인한다.
     */
    SSL_CTX_set_session_cache_mode(c,SSL_SESS_CACHE_OFF);
    SSL_CTX_set_options(c,SSL_OP_NO_TICKET);SSL_CTX_set_num_tickets(c,0);
    if(server){
        if(SSL_CTX_use_certificate_chain_file(c,cert)!=1||SSL_CTX_use_PrivateKey_file(c,key,SSL_FILETYPE_PEM)!=1||SSL_CTX_check_private_key(c)!=1)die("certificate/key");
            if(getenv("KPQC_EXTRA_CERT") && (SSL_CTX_use_certificate_chain_file(c,getenv("KPQC_EXTRA_CERT"))!=1 || SSL_CTX_use_PrivateKey_file(c,getenv("KPQC_EXTRA_KEY"),SSL_FILETYPE_PEM)!=1))die("extra certificate");
    }else{
        /* 클라이언트는 서버 인증서 검증을 수행한다. cert 인자는 서버 인증서 파일이 아니라 신뢰할 CA/인증서 묶음이다.
         */
        SSL_CTX_set_verify(c,SSL_VERIFY_PEER,NULL);
        if(SSL_CTX_load_verify_locations(c,cert,NULL)!=1)die("trust");
    }
    return c;
}
static long status_kib(const char *key){
    char buf[8192];int fd=open("/proc/self/status",O_RDONLY);if(fd<0)return -1;
    ssize_t n=read(fd,buf,sizeof(buf)-1);close(fd);if(n<=0)return -1;buf[n]=0;
    char *p=strstr(buf,key);return p?strtol(p+strlen(key),NULL,10):-1;
}
static int reset_peak(void){int fd=open("/proc/self/clear_refs",O_WRONLY);if(fd<0)return 0;int ok=write(fd,"5",1)==1;close(fd);return ok;}
static SSL_CTX *warm_context=NULL;
static double attempt_ms=0;
static long long mono_ns(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return (long long)t.tv_sec*1000000000+t.tv_nsec;}

static int handshake(int fd,int server,const char *group,const char *sig,const char *cert,const char *key,const char *host,const char *output){
    SSL_CTX *c;
    if(getenv("KPQC_WARM")){
        if(!warm_context)warm_context=context(server,group,sig,cert,key);
        c=warm_context;SSL_CTX_up_ref(c);
    }else c=context(server,group,sig,cert,key);
    SSL *s=SSL_new(c);if(!s)die("SSL_new");
    if(!SSL_set_fd(s,fd))die("SSL_set_fd");
    /* SNI로 서비스 이름을 알리고, 별도로 host와 인증서 이름의 일치를 검증한다. SNI 설정만으로 인증서 검증이 되지는 않는다.
     */
    if(!server&&(!SSL_set_tlsext_host_name(s,"kpqc-lab.internal")||!SSL_set1_host(s,host)))die("hostname");
    struct trace trace={0};SSL_set_msg_callback(s,msg);SSL_set_msg_callback_arg(s,&trace);
    /* 서버의 Provider·SSL 초기화가 끝났음을 평문 1바이트로 알린 뒤 측정을 시작한다.
     * 이 준비 신호는 TLS 표준 메시지가 아닌 실험 장치이므로 일반 HTTPS 클라이언트와 직접 호환되지 않는다.
     */
    char ready='R';
    if(!server && getenv("KPQC_ROUTE")){
        const char *route=getenv("KPQC_ROUTE");
        if(send(fd,route,strlen(route),0)!=(ssize_t)strlen(route)||send(fd,"\n",1,0)!=1)die("route");
    }
    if(server){if(send(fd,&ready,1,0)!=1)die("ready send");}
    else {if(recv(fd,&ready,1,MSG_WAITALL)!=1||ready!='R')die("ready receive");}
    /* CPU는 호출 전후 사용자/커널 시간의 차이로 측정한다. ru_maxrss는 프로세스 생애 최대 RSS이며 차분 메모리가 아니다.
     * Linux 컨테이너의 ru_maxrss 단위는 KiB다. 서버·클라이언트 값을 개별로 기록한다.
     */
    int memory=getenv("KPQC_MEMORY")!=NULL,reset_ok=0;
    long rss_before=-1,anon_before=-1,hwm_before=-1,hwm_after=-1,rss_after=-1,anon_after=-1;
    if(memory){rss_before=status_kib("VmRSS:");anon_before=status_kib("RssAnon:");reset_ok=reset_peak();hwm_before=status_kib("VmHWM:");}
    /* Lab-only service stall precedes SSL_accept; the client waits inside SSL_connect. */
    if(server && getenv("KPQC_TEST_ACCEPT_DELAY_MS"))
        usleep((useconds_t)atoi(getenv("KPQC_TEST_ACCEPT_DELAY_MS"))*1000);
    struct rusage before,after;struct timespec a,b;
    if(getrusage(RUSAGE_SELF,&before))die("getrusage");
    /* 측정 시작: TCP 연결·인증서 준비·위 준비 신호는 이미 끝났다. 시스템 시각 보정의 영향을 피하는 단조 시계를 사용한다.
     */
    clock_gettime(CLOCK_MONOTONIC,&a);
    /* 핵심 측정 대상은 서버 SSL_accept 또는 클라이언트 SSL_connect 한 번이다. HTTP·파일 송수신은 하지 않는다.
     */
    int rc=server?SSL_accept(s):SSL_connect(s);
    /* 측정 끝: 결과 JSON 기록·종료 처리는 이 구간 밖이다. 메시지 관찰 콜백 비용은 SSL 호출 안에 포함된다.
     */
    clock_gettime(CLOCK_MONOTONIC,&b);
    if(getrusage(RUSAGE_SELF,&after))die("getrusage");
    if(memory){hwm_after=status_kib("VmHWM:");rss_after=status_kib("VmRSS:");anon_after=status_kib("RssAnon:");}
    int sslerr=rc==1?SSL_ERROR_NONE:SSL_get_error(s,rc);
    /* SSL 호출 성공 여부와 인증서 검증 결과를 별도 기록한다. 배포 게이트는 클라이언트의 두 조건을 모두 검사한다.
     */
    long verify=SSL_get_verify_result(s);int reused=SSL_session_reused(s);
    X509 *peer=SSL_get1_peer_certificate(s);EVP_PKEY *pub=peer?X509_get_pubkey(peer):NULL;
    const char *keytype=pub?EVP_PKEY_get0_type_name(pub):"none";
    unsigned char digest[EVP_MAX_MD_SIZE];unsigned int digest_len=0;char fingerprint[65]={0};
    if(peer && X509_digest(peer,EVP_sha256(),digest,&digest_len)==1 && digest_len==32)
        for(unsigned int i=0;i<digest_len;i++)snprintf(fingerprint+2*i,3,"%02x",digest[i]);
    const char *group_name=SSL_get0_group_name(s);
    struct tcp_info ti={0};socklen_t tilen=sizeof(ti);getsockopt(fd,IPPROTO_TCP,TCP_INFO,&ti,&tilen);
    FILE *f=fopen(output,getenv("KPQC_JSONL")?"a":"w");if(!f)die("output");
    fprintf(f,"{\"role\":\"%s\",\"success\":%s,\"handshake_ms\":%.6f,\"user_cpu_ms\":%.3f,\"system_cpu_ms\":%.3f,\"cpu_ms\":%.3f,\"process_peak_rss_kib_before\":%ld,\"process_peak_rss_kib_after\":%ld,\"group_code\":%u,\"signature_code\":%u,\"hello_retry_requests\":%u,\"handshake_messages\":%u,\"reused\":%s,\"verify_result\":%ld,\"ssl_error\":%d,\"peer_key_type\":\"%s\",\"tls_version\":\"%s\",\"cipher\":\"%s\"",
      server?"server":"client",rc==1?"true":"false",diff(a,b),tvms(after.ru_utime)-tvms(before.ru_utime),tvms(after.ru_stime)-tvms(before.ru_stime),tvms(after.ru_utime)+tvms(after.ru_stime)-tvms(before.ru_utime)-tvms(before.ru_stime),before.ru_maxrss,after.ru_maxrss,trace.group,trace.signature,trace.hrr,trace.messages,reused?"true":"false",verify,sslerr,keytype,SSL_get_version(s),SSL_get_cipher_name(s));
    /* Append metadata outside the measured interval. */
    fprintf(f,",\"tcp_snd_mss\":%u,\"tcp_rcv_mss\":%u,\"tcp_pmtu\":%u,\"tcp_rtt_us\":%u,\"completed_monotonic_ns\":%lld,\"tcp_ready_and_handshake_ms\":%.6f",ti.tcpi_snd_mss,ti.tcpi_rcv_mss,ti.tcpi_pmtu,ti.tcpi_rtt,(long long)b.tv_sec*1000000000+b.tv_nsec,attempt_ms>0?(b.tv_sec*1000.0+b.tv_nsec/1e6-attempt_ms):0);
    fprintf(f,",\"peer_certificate_sha256\":\"%s\",\"group_name\":\"%s\",\"sent_handshake_bytes\":%zu,\"received_handshake_bytes\":%zu,\"memory_mode\":%s,\"rss_peak_reset_ok\":%s,\"rss_before_kib\":%ld,\"rss_after_kib\":%ld,\"rss_window_baseline_kib\":%ld,\"rss_window_peak_kib\":%ld,\"rss_window_peak_growth_kib\":%ld,\"anon_before_kib\":%ld,\"anon_after_kib\":%ld}\n",fingerprint,group_name?group_name:"unknown",trace.sent_bytes,trace.received_bytes,memory?"true":"false",reset_ok?"true":"false",rss_before,rss_after,hwm_before,hwm_after,reset_ok?hwm_after-hwm_before:-1,anon_before,anon_after);
    fclose(f);
    if(rc!=1)ERR_print_errors_fp(stderr);
    /* TLS 종료 알림은 타이머를 멈춘 뒤 보낸다. 종료 처리 시간은 handshake_ms에 포함되지 않는다.
     */
    if(rc==1)SSL_shutdown(s); /* outside measurement; no application data */
    EVP_PKEY_free(pub);X509_free(peer);SSL_free(s);SSL_CTX_free(c);close(fd);
    return rc==1?0:1;
}
static void socket_options(int fd){int one=1;struct timeval tv={15,0};
    setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&one,sizeof(one));
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&tv,sizeof(tv));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&tv,sizeof(tv));
}
int main(int argc,char **argv){
    if(argc==2 && !strcmp(argv[1],"memory-selftest")){
        const size_t size=16*1024*1024;long before=status_kib("VmRSS:");int ok=reset_peak();long base=status_kib("VmHWM:");
        volatile unsigned char *v=mmap(NULL,size,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS,-1,0);
        if(v==MAP_FAILED)return 2;
        for(size_t i=0;i<size;i+=4096)v[i]=1;
        long peak=status_kib("VmHWM:");
        printf("{\"reset_ok\":%s,\"before_kib\":%ld,\"baseline_kib\":%ld,\"peak_kib\":%ld,\"growth_kib\":%ld,\"touched_kib\":%zu}\n",ok?"true":"false",before,base,peak,peak-base,size/1024);
        munmap((void*)v,size);return ok && peak-base>size/1024*0.8 && peak-base<size/1024*1.3 ? 0:1;
    }
    /* role group sig cert key ip port output count host */
    if(argc!=11){fprintf(stderr,"role group sig cert key ip port output count host\n");return 2;}
    signal(SIGPIPE,SIG_IGN);alarm(600);
    int server=!strcmp(argv[1],"server"),fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0)die("socket");socket_options(fd);
    struct sockaddr_in addr={.sin_family=AF_INET,.sin_port=htons(atoi(argv[7]))};
    if(inet_pton(AF_INET,argv[6],&addr.sin_addr)!=1)die("address");
    /* 클라이언트 TCP connect를 마친 뒤 handshake()로 들어가므로 TCP 연결 수립 시간은 측정에서 제외된다.
     */
    if(!server){
        int count=atoi(argv[9]),failed=0;char output[1024];
        int load=getenv("KPQC_LOAD_SECONDS")!=NULL;
        long long deadline=0;
        if(load){
            setenv("KPQC_WARM","1",1);setenv("KPQC_JSONL","1",1);
            warm_context=context(0,argv[2],argv[3],argv[4],argv[5]);
            snprintf(output,sizeof(output),"%s.ready",argv[8]);FILE *rf=fopen(output,"w");if(!rf)die("client ready");fclose(rf);
            while(access(getenv("KPQC_START_FILE"),F_OK))usleep(1000);
            deadline=mono_ns()+(long long)(atof(getenv("KPQC_LOAD_SECONDS"))*1e9);
        }
        for(int i=0;i<count;i++){
            if(load && (mono_ns()>=deadline || (getenv("KPQC_STOP_FILE") && !access(getenv("KPQC_STOP_FILE"),F_OK))))break;
            attempt_ms=mono_ns()/1e6;
            if(i){fd=socket(AF_INET,SOCK_STREAM,0);socket_options(fd);}
            if(connect(fd,(struct sockaddr*)&addr,sizeof(addr)))die("connect");
            if(load)snprintf(output,sizeof(output),"%s.jsonl",argv[8]);else if(count>1)snprintf(output,sizeof(output),"%s-%03d.json",argv[8],i);else snprintf(output,sizeof(output),"%s",argv[8]);
            failed+=handshake(fd,0,argv[2],argv[3],argv[4],argv[5],argv[10],output)!=0;
        }
        return failed?1:0;
    }
    int one=1;setsockopt(fd,SOL_SOCKET,SO_REUSEADDR,&one,sizeof(one));
    if(bind(fd,(struct sockaddr*)&addr,sizeof(addr))||listen(fd,256))die("listen");
    char name[1024];snprintf(name,sizeof(name),"%s.ready",argv[8]);FILE *r=fopen(name,"w");if(!r)die("ready file");fputs("ready",r);fclose(r);
    /* Opt-in prefork service: each worker reuses its own context, no shared SSL object. */
    if(getenv("KPQC_SERVER_WORKERS")){
        int workers=atoi(getenv("KPQC_SERVER_WORKERS"));if(workers<1||workers>64)die("worker count");
        for(int w=0;w<workers;w++){
            pid_t child=fork();if(child<0)die("worker fork");
            if(!child){
                setenv("KPQC_WARM","1",1);setenv("KPQC_JSONL","1",1);
                warm_context=context(1,argv[2],argv[3],argv[4],argv[5]);
                snprintf(name,sizeof(name),"%s-worker-%d.jsonl",argv[8],w);
                while(1){int conn=accept(fd,NULL,NULL);
                    /* An idle listener's receive timeout is not a service failure. */
                    if(conn<0){if(errno==EINTR||errno==EAGAIN||errno==EWOULDBLOCK||errno==ECONNABORTED)continue;die("worker accept");}
                    socket_options(conn);
                    handshake(conn,1,argv[2],argv[3],argv[4],argv[5],argv[10],name);}
            }
        }
        while(wait(NULL)>0){}close(fd);return 0;
    }
    int failed=0,count=atoi(argv[9]);
    for(int i=0;i<count;i++){
        int conn=accept(fd,NULL,NULL);if(conn<0)die("accept");socket_options(conn);
        /* 연결마다 새 자식에서 TLS를 처리하고 기다린다. 순차 실험이며 동시 접속 처리량 시험이 아니다.
         * 자식 프로세스별 자원 기록으로 이전 연결의 메모리 최대값이 누적되는 것을 줄인다.
         */
        if(getenv("KPQC_WARM")){snprintf(name,sizeof(name),"%s-%03d.json",argv[8],i);failed+=handshake(conn,1,argv[2],argv[3],argv[4],argv[5],argv[10],name)!=0;continue;}
        pid_t p=fork();if(p<0)die("fork");
        if(!p){close(fd);alarm(20);snprintf(name,sizeof(name),"%s-%03d.json",argv[8],i);int rc=handshake(conn,1,argv[2],argv[3],argv[4],argv[5],argv[10],name);_exit(rc);}
        close(conn);int status;if(waitpid(p,&status,0)<0)die("waitpid");if(!WIFEXITED(status)||WEXITSTATUS(status))failed++;
    }
    close(fd);return failed?1:0;
}
