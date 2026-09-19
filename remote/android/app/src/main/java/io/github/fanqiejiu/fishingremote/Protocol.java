package io.github.fanqiejiu.fishingremote;

import java.net.URI;
import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.Map;

/** Pure Java validation, shared by scanned, pasted and deep-linked pairing. */
public final class Protocol {
    private Protocol() {}
    public static String relay(String input) {
        String s=input.trim().replaceAll("/+$", "");
        try {
            URI u=new URI(s);
            if (!"https".equals(u.getScheme()) || u.getHost()==null || u.getUserInfo()!=null ||
                u.getQuery()!=null || u.getFragment()!=null || !u.getPath().isEmpty() ||
                s.length()>240 || u.getPort()>65535) throw new Exception();
            return s;
        } catch (Exception e) { throw new IllegalArgumentException("请输入不含路径或参数的 HTTPS 中转地址"); }
    }
    public static Map<String,String> pair(String link) {
        try {
            URI u=new URI(link.trim());
            if (link.length()>2048 || !"okfishing".equals(u.getScheme()) || !"pair".equals(u.getHost()) ||
                u.getUserInfo()!=null || u.getPort()!=-1 || !u.getPath().isEmpty() || u.getFragment()!=null) throw new Exception();
            Map<String,String> values=new HashMap<>();
            for (String part:u.getRawQuery().split("&")) {
                String[] item=part.split("=",2);
                String key=URLDecoder.decode(item[0], StandardCharsets.UTF_8.name());
                String value=URLDecoder.decode(item[1], StandardCharsets.UTF_8.name());
                if (values.put(key,value)!=null) throw new Exception();
            }
            if (!"1".equals(values.get("v")) || !values.getOrDefault("code", "").matches("[a-f0-9]{48}")) throw new Exception();
            values.put("relay",relay(values.getOrDefault("relay", "")));
            return values;
        } catch (Exception e) { throw new IllegalArgumentException("这不是有效的钓鱼远程配对二维码"); }
    }
    public static boolean newer(String remote, String local) {
        if (!remote.matches("[0-9]+(?:\\.[0-9]+){1,3}")) return false;
        String[] a=remote.split("\\."), b=local.split("-",2)[0].split("\\.");
        try {
            for(int i=0;i<Math.max(a.length,b.length);i++) {
                int x=i<a.length?Integer.parseInt(a[i]):0, y=i<b.length?Integer.parseInt(b[i]):0;
                if(x!=y) return x>y;
            }
        } catch(NumberFormatException ignored) {}
        return false;
    }
}
