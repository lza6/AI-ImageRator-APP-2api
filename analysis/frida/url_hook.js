Java.perform(function() {
    // java.net.URL 全量
    var URL = Java.use('java.net.URL');
    URL.$init.overload('java.lang.String').implementation = function(s) {
        console.log('[JAVA-URL] ' + s);
        return this.$init(s);
    };
    // OkHttp RealCall
    try {
        var RC = Java.use('okhttp3.internal.connection.RealCall');
        RC.getResponseWithInterceptorChain.implementation = function() {
            console.log('[CALL] ' + this.request().url());
            return this.getResponseWithInterceptorChain();
        };
    } catch(e){}
    // Volley
    try {
        var R = Java.use('com.android.volley.Request');
        R.getUrl.implementation = function() {
            var u = this.getUrl();
            console.log('[VOLLEY] ' + u);
            return u;
        };
    } catch(e){}
    // Retrofit
    try {
        var RH = Java.use('retrofit2.RequestFactory');
        RH.create.implementation = function(args) {
            var rq = this.create(args);
            console.log('[RETROFIT] ' + rq.url());
            return rq;
        };
    } catch(e){}
    // 防崩
    var Thread = Java.use('java.lang.Thread');
    var H = Java.registerClass({name:'com.nocrash.HY', implements:[Java.use('java.lang.Thread$UncaughtExceptionHandler')],
        methods:{uncaughtException:function(t,e){console.log('[SUP] '+e);}}});
    Thread.setDefaultUncaughtExceptionHandler(H.$new());
    var RT = Java.use('java.lang.Runtime'); RT.exit.implementation=function(c){console.log('[BLOCK] exit');};
    var Sys = Java.use('java.lang.System'); Sys.exit.implementation=function(c){console.log('[BLOCK] sys.exit');};
    try { var HUC = Java.use('com.android.okhttp.internal.huc.HttpURLConnectionImpl');
        HUC.getInputStream.implementation = function() {
            try { return this.getInputStream(); }
            catch(e) { var B=Java.use('java.io.ByteArrayInputStream'); var S=Java.use('java.lang.String');
                return B.$new(S.$new('{"version":999}').getBytes()); }
        };
    } catch(e){}
    console.log('[+] url_hook ready');
});
