Java.perform(function() {
    // 1. SP 全量写入监控
    var Editor = Java.use('android.app.SharedPreferencesImpl$EditorImpl');
    Editor.putString.overload('java.lang.String','java.lang.String').implementation = function(k, v) {
        if (v && v.length > 3 && v.length < 500) {
            console.log('[SP-PUT] ' + k + ' = ' + v);
            send({type:'sp', key:k, value:v});
        }
        return this.putString(k, v);
    };
    // 2. 全部出站 URL 监控
    var Builder = Java.use('okhttp3.Request$Builder');
    Builder.url.overload('java.lang.String').implementation = function(u) {
        console.log('[URL] ' + u);
        send({type:'url', value:u});
        return this.url(u);
    };
    Builder.url.overload('okhttp3.HttpUrl').implementation = function(u) {
        console.log('[URL-OBJ] ' + u);
        send({type:'url', value:String(u)});
        return this.url(u);
    };
    // 3. Header 全量
    Builder.addHeader.overload('java.lang.String','java.lang.String').implementation = function(n, v) {
        if (n && ['authorization','x-api-key','api-key','key','token','x-token'].indexOf(n.toLowerCase())>=0) {
            console.log('[HDR] ' + n + ': ' + v);
            send({type:'hdr', name:n, value:v});
        }
        return this.addHeader(n, v);
    };
    Builder.header.overload('java.lang.String','java.lang.String').implementation = function(n, v) {
        if (n && ['authorization','x-api-key','api-key','key','token','x-token'].indexOf(n.toLowerCase())>=0) {
            console.log('[HDR-H] ' + n + ': ' + v);
            send({type:'hdr', name:n, value:v});
        }
        return this.header(n, v);
    };
    // 4. 防崩
    var Thread = Java.use('java.lang.Thread');
    var H = Java.registerClass({name:'com.nocrash.HZ', implements:[Java.use('java.lang.Thread$UncaughtExceptionHandler')],
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
    console.log('[+] sp_hook ready');
});
