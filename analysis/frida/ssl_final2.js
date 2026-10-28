Java.perform(function() {
    var Thread = Java.use('java.lang.Thread');
    var H = Java.registerClass({name:'com.nocrash.HG', implements:[Java.use('java.lang.Thread$UncaughtExceptionHandler')],
        methods:{uncaughtException:function(t,e){console.log('[SUP] '+e); send({type:'sup',msg:String(e)});}}});
    Thread.setDefaultUncaughtExceptionHandler(H.$new());
    var RT = Java.use('java.lang.Runtime'); RT.exit.implementation=function(c){console.log('[BLOCK] exit');};
    var Sys = Java.use('java.lang.System'); Sys.exit.implementation=function(c){console.log('[BLOCK] sys.exit');};
    try { var P = Java.use('android.os.Process'); P.killProcess.implementation=function(p){console.log('[BLOCK] kill');}; } catch(e){}

    try {
        var HUC = Java.use('com.android.okhttp.internal.huc.HttpURLConnectionImpl');
        HUC.getInputStream.implementation = function() {
            try { return this.getInputStream(); }
            catch(e) {
                var BAIS = Java.use('java.io.ByteArrayInputStream');
                var Str = Java.use('java.lang.String');
                return BAIS.$new(Str.$new('{"version":999}').getBytes());
            }
        };
    } catch(e) {}

    // OkHttp3 pinner (app 的主网络栈是 okhttp3)
    try {
        var CP = Java.use('okhttp3.CertificatePinner');
        CP.check.overload('java.lang.String','java.util.List').implementation = function(h,p){ console.log('[PIN-BYPASS] '+h); };
        CP.check$okhttp.implementation = function(h,p){ console.log('[PIN-BYPASS2] '+h); };
    } catch(e) {}
    // okhttp (内建) pinner
    try {
        var CP2 = Java.use('com.android.okhttp.CertificatePinner');
        CP2.check.overload('java.lang.String','java.util.List').implementation = function(h,p){ console.log('[PIN2] '+h); };
    } catch(e) {}
    // TLS trust 全放行
    try {
        var X509 = Java.use('javax.net.ssl.X509TrustManager');
        var SC = Java.use('javax.net.ssl.SSLContext');
        var TM = Java.registerClass({name:'com.trust.TMG', implements:[X509], methods:{
            checkClientTrusted:function(c,a){}, checkServerTrusted:function(c,a){}, getAcceptedIssuers:function(){return [];}}});
        var ctx=SC.getInstance('TLS'); ctx.init(null,[TM.$new()],null); SC.setDefault(ctx);
    } catch(e) {}
    // TrustManagerImpl verify 直接 true
    try {
        var TMI = Java.use('com.android.org.conscrypt.TrustManagerImpl');
        TMI.verifyChain.implementation = function(chain, authType, host, clientAuth, ocspData, tlsSctData) {
            console.log('[TM-OK] ' + host);
            return chain;
        };
    } catch(e) { console.log('[-] TMI ' + e); }

    var B = Java.use('okhttp3.Request$Builder');
    B.addHeader.overload('java.lang.String','java.lang.String').implementation=function(n,v){
        if(n&&n.toLowerCase()==='authorization'&&v&&v.length>4){console.log('[TOKEN] '+v); send({type:'token',value:v});}
        return this.addHeader(n,v);};
    B.header.overload('java.lang.String','java.lang.String').implementation=function(n,v){
        if(n&&n.toLowerCase()==='authorization'&&v&&v.length>4){console.log('[TOKEN-H] '+v); send({type:'token',value:v});}
        return this.header(n,v);};
    console.log('[+] final2 ready');
});
