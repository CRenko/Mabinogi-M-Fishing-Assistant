package io.github.fanqiejiu.fishingremote;

import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

final class Api {
    static final String REPO="fanqiejiu/Mabinogi-M-Fishing-Assistant";
    static final String RELEASES="https://github.com/"+REPO+"/releases";
    static class Failure extends Exception {
        final int status;
        Failure(int status, String message) { super(message); this.status=status; }
    }
    static String request(String url,String method,JSONObject body,String token,int limit) throws Exception {
        HttpURLConnection connection=(HttpURLConnection)new URL(url).openConnection();
        connection.setInstanceFollowRedirects(false);
        connection.setConnectTimeout(8000); connection.setReadTimeout(8000);
        connection.setRequestMethod(method);
        connection.setRequestProperty("Accept","application/json");
        connection.setRequestProperty("User-Agent","ok-fishing-remote/"+BuildConfig.VERSION_NAME);
        if(!token.isEmpty()) connection.setRequestProperty("Authorization","Bearer "+token);
        try {
            if(body!=null) {
                connection.setDoOutput(true); connection.setRequestProperty("Content-Type","application/json");
                byte[] bytes=body.toString().getBytes(StandardCharsets.UTF_8);
                connection.setFixedLengthStreamingMode(bytes.length);
                try(var out=connection.getOutputStream()) { out.write(bytes); }
            }
            int status=connection.getResponseCode();
            if(status<200||status>=300) {
                String message=switch(status) {
                    case 401 -> "设备绑定已失效，请在电脑上重新生成二维码";
                    case 403 -> "访问被拒绝，配对链接可能已过期或已使用";
                    case 429 -> "请求过于频繁，请一分钟后再试";
                    default -> "服务暂不可用（HTTP "+status+"）";
                };
                throw new Failure(status,message);
            }
            try(InputStream in=connection.getInputStream();ByteArrayOutputStream out=new ByteArrayOutputStream()) {
                byte[] buffer=new byte[4096]; int count;
                while((count=in.read(buffer))!=-1) {
                    if(out.size()+count>limit) throw new Failure(0,"响应过大，请检查中转服务");
                    out.write(buffer,0,count);
                }
                return out.toString(StandardCharsets.UTF_8.name());
            }
        } finally { connection.disconnect(); }
    }
    static JSONObject relay(String relay,String path,String method,JSONObject body,String token) throws Exception {
        return new JSONObject(request(Protocol.relay(relay)+path,method,body,token,8192));
    }
    static JSONObject update() throws Exception {
        JSONArray releases=new JSONArray(request("https://api.github.com/repos/"+REPO+"/releases?per_page=30","GET",null,"",524288));
        JSONObject best=null;
        for(int i=0;i<releases.length();i++) {
            JSONObject release=releases.getJSONObject(i);
            String tag=release.optString("tag_name"), prefix="android-v";
            if(!tag.startsWith(prefix)||release.optBoolean("draft")||release.optBoolean("prerelease")) continue;
            String version=tag.substring(prefix.length());
            if(!Protocol.newer(version,BuildConfig.VERSION_NAME)) continue;
            boolean apk=false;
            JSONArray assets=release.optJSONArray("assets");
            if(assets!=null) for(int j=0;j<assets.length();j++) {
                if(assets.getJSONObject(j).optString("name").equals("ok-MabinogiFishing-remote-v"+version+".apk")) apk=true;
            }
            if(apk && (best==null || Protocol.newer(version,best.getString("version"))))
                best=new JSONObject().put("version",version).put("body",release.optString("body"))
                    .put("url",RELEASES+"/tag/android-v"+version);
        }
        return best;
    }
    static String error(Exception error) {
        return error instanceof Failure ? error.getMessage() : "连接失败，请检查网络；电脑上的钓鱼不受影响";
    }
}
