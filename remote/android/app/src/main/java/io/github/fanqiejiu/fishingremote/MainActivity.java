package io.github.fanqiejiu.fishingremote;

import android.app.AlertDialog;
import android.content.ClipboardManager;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.Gravity;
import android.view.View;
import android.view.WindowInsets;
import android.widget.Button;
import android.widget.CheckBox;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;
import androidx.activity.ComponentActivity;
import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import com.journeyapps.barcodescanner.ScanContract;
import com.journeyapps.barcodescanner.ScanOptions;
import org.json.JSONObject;
import java.security.SecureRandom;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class MainActivity extends ComponentActivity {
    // Memory-only sessions survive rotation, but not process death or an explicit exit.
    private static final Session S=new Session();
    private static class Session {
        JSONObject device, status;
        boolean loaded, remembered, polling, unauthorized, pairing;
        long generation, nextPoll, fetchedAt;
        String connectionError="", pendingCode="", pendingToken="";
    }
    private final Handler handler=new Handler(Looper.getMainLooper());
    private final ExecutorService network=Executors.newSingleThreadExecutor();
    private final ExecutorService updateNetwork=Executors.newSingleThreadExecutor();
    private SharedPreferences preferences;
    private SecureStore secureStore;
    private LinearLayout root, content;
    private ScrollView scroll;
    private int page=0, background, surface, textColor, muted, accent, border;
    private boolean dark, resumed, updateBusy, showingStale;
    private JSONObject pendingUpdate;
    private long lastUpdateAttempt;
    private String updateMessage="手机端与电脑端分别检查更新";
    private String probeMessage="测试前关闭系统 VPN / 代理，结果仅代表当前网络。";
    private boolean probeBusy;
    private AlertDialog activeDialog;
    private final ActivityResultLauncher<ScanOptions> scanner=registerForActivityResult(new ScanContract(), result -> {
        if(result.getContents()!=null) confirmPair(result.getContents());
    });
    private final Runnable ticker=new Runnable() {
        @Override public void run() {
            if(!resumed) return;
            if(S.device!=null && !S.unauthorized && SystemClock.elapsedRealtime()>=S.nextPoll) poll(false);
            if(page==0 && S.status!=null && !S.polling && !showingStale && statusAge()>180) renderStatusOnly();
            if(pendingUpdate!=null && !S.pairing && (activeDialog==null || !activeDialog.isShowing())) {
                JSONObject release=pendingUpdate; pendingUpdate=null; showUpdate(release);
            }
            handler.postDelayed(this,1000);
        }
    };

    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        preferences=getSharedPreferences("settings",MODE_PRIVATE);
        secureStore=new SecureStore(getApplicationContext());
        getOnBackPressedDispatcher().addCallback(this,new OnBackPressedCallback(true) {
            @Override public void handleOnBackPressed() {
                if(page!=0) { page=0; render(); } else finish();
            }
        });
        if(saved!=null) page=saved.getInt("page",0);
        if(!S.loaded) {
            S.loaded=true;
            try { S.device=secureStore.load(); S.remembered=S.device!=null; }
            catch(Exception e) { toast("保存的设备信息不可用，请重新扫码"); }
        }
        render();
        if(getIntent().getData()!=null) {
            String link=getIntent().getDataString(); getIntent().setData(null);
            handler.post(()->confirmPair(link));
        }
        if(preferences.getBoolean("auto_update",true) &&
            System.currentTimeMillis()-preferences.getLong("update_checked_at",0)>21600000) checkUpdate(false);
    }
    @Override protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent); setIntent(intent);
        if(intent.getData()!=null) { String link=intent.getDataString(); intent.setData(null); confirmPair(link); }
    }
    @Override protected void onResume() { super.onResume(); resumed=true; handler.post(ticker); }
    @Override protected void onPause() { resumed=false; handler.removeCallbacks(ticker); super.onPause(); }
    @Override protected void onSaveInstanceState(Bundle state) { state.putInt("page",page); super.onSaveInstanceState(state); }
    @Override protected void onDestroy() {
        handler.removeCallbacks(ticker);
        if(activeDialog!=null) activeDialog.dismiss();
        if(isFinishing() && !S.remembered) { S.device=null; S.status=null; S.generation++; }
        network.shutdown();
        updateNetwork.shutdown();
        super.onDestroy();
    }
    private int dp(float n) { return Math.round(n*getResources().getDisplayMetrics().density); }
    private void colors() {
        String selected=preferences.getString("theme","system");
        dark="night".equals(selected)||("system".equals(selected)&&
            (getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)==Configuration.UI_MODE_NIGHT_YES);
        background=Color.parseColor(dark?"#09111F":"#F3F7F6");
        surface=Color.parseColor(dark?"#111F30":"#FFFFFF");
        textColor=Color.parseColor(dark?"#EFF6FC":"#182D35");
        muted=Color.parseColor(dark?"#9BAFC5":"#647B83");
        accent=Color.parseColor(dark?"#65E1B2":"#087D5C");
        border=Color.parseColor(dark?"#263A51":"#DFE9E5");
    }
    private GradientDrawable box(int color,int radius) {
        GradientDrawable shape=new GradientDrawable(); shape.setColor(color);
        shape.setCornerRadius(dp(radius)); shape.setStroke(dp(1),border); return shape;
    }
    private LinearLayout column() {
        LinearLayout result=new LinearLayout(this); result.setOrientation(LinearLayout.VERTICAL); return result;
    }
    private TextView label(String text,int size,int color,boolean bold) {
        TextView view=new TextView(this); view.setText(text); view.setTextSize(size); view.setTextColor(color);
        view.setLineSpacing(dp(3),1); if(bold) view.setTypeface(Typeface.DEFAULT,Typeface.BOLD);
        return view;
    }
    private void gap(LinearLayout target,int height) { View v=new View(this); target.addView(v,new LinearLayout.LayoutParams(1,dp(height))); }
    private LinearLayout card(String title) {
        LinearLayout card=column(); card.setPadding(dp(20),dp(20),dp(20),dp(20)); card.setBackground(box(surface,20));
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2); lp.bottomMargin=dp(14); content.addView(card,lp);
        if(!title.isEmpty()) { card.addView(label(title,17,textColor,true)); gap(card,12); }
        return card;
    }
    private Button button(String caption,boolean primary,Runnable click) {
        Button b=new Button(this); b.setText(caption); b.setAllCaps(false); b.setTextSize(14);
        b.setTextColor(primary?(dark?Color.parseColor("#09251C"):Color.WHITE):textColor);
        b.setBackground(box(primary?accent:surface,14)); b.setMinHeight(dp(50));
        b.setPadding(dp(12),dp(10),dp(12),dp(10)); b.setOnClickListener(v->click.run());
        return b;
    }
    private void action(LinearLayout container,String caption,boolean primary,Runnable click) {
        Button b=button(caption,primary,click);
        LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(-1,-2); lp.topMargin=dp(10); container.addView(b,lp);
    }
    private void detail(LinearLayout container,String name,String value) {
        LinearLayout row=new LinearLayout(this); row.setGravity(Gravity.CENTER_VERTICAL); row.setPadding(0,dp(9),0,dp(9));
        row.addView(label(name,13,muted,false),new LinearLayout.LayoutParams(0,-2,1));
        TextView right=label(value,14,textColor,true); right.setGravity(Gravity.END);
        row.addView(right,new LinearLayout.LayoutParams(0,-2,1)); container.addView(row);
    }
    private void render() {
        colors();
        root=column(); root.setBackgroundColor(background);
        root.setOnApplyWindowInsetsListener((v,insets)-> {
            if(android.os.Build.VERSION.SDK_INT>=30) {
                var bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.ime());
                root.setPadding(bars.left,bars.top,bars.right,bars.bottom);
            } else root.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),
                                   insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        if(android.os.Build.VERSION.SDK_INT>=30) {
            getWindow().setDecorFitsSystemWindows(false);
        }
        LinearLayout header=column(); header.setPadding(dp(24),dp(20),dp(24),dp(14));
        TextView eyebrow=label("OK FISHING  /  REMOTE",11,accent,true); eyebrow.setLetterSpacing(.14f); header.addView(eyebrow);
        gap(header,8); header.addView(label(new String[]{"钓鱼状态","我的设备","设置"}[page],28,textColor,true));
        gap(header,4); header.addView(label(new String[]{"不在电脑旁，也能看一眼。","连接只属于你的那台电脑。","按你的习惯，轻松查看。"}[page],13,muted,false));
        root.addView(header);
        scroll=new ScrollView(this); scroll.setFillViewport(true); scroll.setClipToPadding(false);
        content=column(); content.setPadding(dp(20),dp(6),dp(20),dp(16)); scroll.addView(content);
        root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        if(page==0) statusPage(); else if(page==1) devicePage(); else settingsPage();
        LinearLayout nav=new LinearLayout(this); nav.setPadding(dp(12),dp(8),dp(12),dp(10)); nav.setBackgroundColor(surface);
        String[] titles={"◉  状态","▣  设备","⚙  设置"};
        for(int i=0;i<3;i++) {
            final int target=i;
            TextView item=label(titles[i],14,i==page?accent:muted,i==page); item.setGravity(Gravity.CENTER);
            item.setBackground(box(i==page?(dark?Color.parseColor("#183B36"):Color.parseColor("#E4F5ED")):surface,14));
            LinearLayout.LayoutParams lp=new LinearLayout.LayoutParams(0,dp(48),1); lp.setMargins(dp(4),0,dp(4),0);
            nav.addView(item,lp); item.setContentDescription(new String[]{"状态","设备","设置"}[i]);
            item.setOnClickListener(v->{page=target;render();});
        }
        root.addView(nav); setContentView(root); root.requestApplyInsets();
        if(android.os.Build.VERSION.SDK_INT>=30) {
            var controller=getWindow().getDecorView().getWindowInsetsController();
            if(controller!=null) {
                int lightBars=android.view.WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                    |android.view.WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                controller.setSystemBarsAppearance(dark?0:lightBars,lightBars);
            }
        }
    }
    private void renderStatusOnly() {
        if(page!=0 || content==null) return;
        int y=scroll.getScrollY(); content.removeAllViews(); statusPage(); scroll.scrollTo(0,y);
    }
    private void statusPage() {
        if(S.device==null) {
            LinearLayout welcome=card(""); welcome.addView(label("让挂机状态\n随身可见",27,textColor,true)); gap(welcome,14);
            welcome.addView(label("先在电脑助手的设置里激活中转，生成配对二维码，再用手机连接。",15,muted,false));
            action(welcome,"扫描电脑二维码",true,this::scan);
            action(welcome,"粘贴配对链接",false,this::pastePair);
            LinearLayout privacy=card("只看状态，不接管电脑");
            privacy.addView(label("不会上传聊天、截图或背包内容，也不会从手机触发游戏按键。",14,muted,false));
            return;
        }
        JSONObject payload=S.status==null?null:S.status.optJSONObject("status");
        long age=statusAge();
        boolean stale=S.status==null||S.status.optBoolean("stale")||age>180;
        showingStale=stale;
        boolean problem=stale||!S.connectionError.isEmpty()||S.unauthorized;
        LinearLayout hero=card("");
        hero.addView(label(problem?"●  状态待确认":"●  中转已连接",12,problem?Color.parseColor(dark?"#F0C677":"#956410"):accent,true));
        gap(hero,12);
        String state=payload==null?"尚未收到状态":stateName(payload.optString("state"));
        hero.addView(label(S.unauthorized?"绑定已失效":(stale?"状态已过期":state),29,textColor,true));
        gap(hero,10);
        String note=!S.connectionError.isEmpty()?S.connectionError:(stale?"不能确认电脑是否仍在钓鱼，请检查电脑或网络。":"电脑和手机约每分钟同步一次，并非实时画面。");
        hero.addView(label(note,14,muted,false));
        if(problem && payload!=null) { gap(hero,10); hero.addView(label("上次状态 · "+state,14,muted,false)); }
        long received=S.status==null?0:S.status.optLong("received_at");
        detail(hero,"最后上报",received==0?"尚无记录":time(received));
        detail(hero,"连接保留",S.remembered?"已记住此设备":"仅本次使用");
        action(hero,S.polling?"正在刷新…":"刷新状态",true,()->poll(true));
        if(payload!=null) {
            LinearLayout info=card("钓鱼概况");
            detail(info,"校准",payload.optBoolean("calibrated")?"已校准":"未校准");
            detail(info,"钓鱼模式",switch(payload.optString("strategy")) {
                case "fixed_delay" -> "模式二 · 定时"; case "instant" -> "模式三 · 即收"; default -> "模式一 · 反弹";
            });
            detail(info,"识别方式","pixel".equals(payload.optString("recognition"))?"旧像素兼容":"OK 框架");
            detail(info,"电脑端版本",payload.optString("version","—"));
            String reason=reasonName(payload.optString("reason"));
            if(!reason.isEmpty()) { gap(info,8); info.addView(label("停止原因 · "+reason,14,muted,false)); }
        }
    }
    private void devicePage() {
        LinearLayout device=card(S.device==null?"还没有绑定设备":"当前电脑");
        device.addView(label(S.device==null?"在电脑端生成二维码后，扫描或粘贴配对链接。":S.device.optString("id"),14,muted,false));
        if(S.device!=null) {
            detail(device,"保存方式",S.remembered?"已加密记住":"临时连接");
            gap(device,8); device.addView(label("中转地址\n"+S.device.optString("relay"),13,muted,false));
        }
        action(device,"扫描配对二维码",true,this::scan);
        action(device,"粘贴配对链接",false,this::pastePair);
        if(S.device!=null) action(device,"忘记此设备",false,this::forget);
        LinearLayout help=card("配对与激活");
        help.addView(label("1. 电脑：设置 → 手机远程查看，输入管理员给你的激活码。\n\n2. 打开状态上报，生成二维码。\n\n3. 手机：扫描后确认中转地址，并选择是否记住此设备。\n\n二维码 10 分钟内有效。重新生成会解除旧手机绑定。",14,muted,false));
    }
    private CheckBox checkbox(String title,boolean checked) {
        CheckBox view=new CheckBox(this); view.setText(title); view.setTextColor(textColor); view.setTextSize(14);
        view.setButtonTintList(ColorStateList.valueOf(accent)); view.setChecked(checked); view.setMinHeight(dp(48)); return view;
    }
    private void settingsPage() {
        LinearLayout theme=card("外观");
        String selected=preferences.getString("theme","system");
        String[] keys={"system","day","night"}, names={"跟随系统","日间主题","夜间主题"};
        for(int i=0;i<keys.length;i++) {
            final String key=keys[i];
            action(theme,(key.equals(selected)?"✓  ":"")+names[i],key.equals(selected),()->{
                preferences.edit().putString("theme",key).apply(); render();
            });
        }
        LinearLayout relay=card("中转服务");
        relay.addView(label(S.device==null?"尚未连接中转":S.device.optString("relay"),14,muted,false));
        relay.addView(label("官方中转使用激活码控制试验名额。自建中转在电脑端设置地址，手机扫描其二维码即可切换；不会把旧密钥发送到新地址。",13,muted,false));
        action(relay,"连接官方 / 自建中转",false,()->{page=1;render();});
        EditText address=new EditText(this);
        address.setTextColor(textColor); address.setHintTextColor(muted); address.setSingleLine(true);
        address.setInputType(android.text.InputType.TYPE_CLASS_TEXT|android.text.InputType.TYPE_TEXT_VARIATION_URI);
        address.setHint("https://中转地址");
        address.setText(S.device==null?preferences.getString("probe_relay",BuildConfig.OFFICIAL_RELAY):S.device.optString("relay"));
        relay.addView(address); relay.addView(label(probeMessage,12,muted,false));
        action(relay,probeBusy?"正在测试…":"测试中转连接",false,()->probe(address.getText().toString()));
        LinearLayout updates=card("应用更新"); detail(updates,"当前版本","v"+BuildConfig.VERSION_NAME);
        CheckBox auto=checkbox("启动时检查新版本",preferences.getBoolean("auto_update",true));
        auto.setOnCheckedChangeListener((v,checked)->preferences.edit().putBoolean("auto_update",checked).apply());
        updates.addView(auto); updates.addView(label(updateMessage,13,muted,false));
        action(updates,updateBusy?"正在检查…":"检查更新",true,()->checkUpdate(true));
        action(updates,"打开 GitHub 项目",false,()->openBrowser("https://github.com/"+Api.REPO));
        LinearLayout privacy=card("隐私与连接");
        privacy.addView(label("只保存最新状态，不上传游戏画面。勾选“记住此设备”后，访问凭据由 Android 密钥库加密保护。\n\n仅在手机端打开时刷新，首版不提供锁屏即时通知。断网不影响电脑继续钓鱼。",14,muted,false));
        if(S.device!=null) action(privacy,"忘记此设备",false,this::forget);
    }
    private void scan() {
        if(S.pairing) { toast("正在配对，请稍候"); return; }
        scanner.launch(new ScanOptions().setDesiredBarcodeFormats(ScanOptions.QR_CODE).setPrompt("扫描电脑助手中的配对二维码")
            .setBeepEnabled(false).setBarcodeImageEnabled(false).setOrientationLocked(false));
    }
    private void pastePair() {
        ClipboardManager clipboard=(ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
        String text=clipboard.hasPrimaryClip()&&clipboard.getPrimaryClip().getItemCount()>0?
            clipboard.getPrimaryClip().getItemAt(0).coerceToText(this).toString():"";
        EditText input=new EditText(this); input.setSingleLine(false); input.setTextColor(textColor);
        input.setText(text.startsWith("okfishing://")?text:""); input.setHint("粘贴电脑端复制的配对链接"); input.setHintTextColor(muted);
        LinearLayout view=dialogContent(); view.addView(input);
        showDialog("粘贴配对链接",view,"下一步",()->confirmPair(input.getText().toString()));
    }
    private LinearLayout dialogContent() { LinearLayout view=column(); view.setPadding(dp(22),dp(10),dp(22),dp(12)); return view; }
    private AlertDialog showDialog(String title,View view,String action,Runnable confirmed) {
        if(activeDialog!=null) activeDialog.dismiss();
        android.view.ContextThemeWrapper context=new android.view.ContextThemeWrapper(this,
            dark?android.R.style.Theme_Material_Dialog_Alert:android.R.style.Theme_Material_Light_Dialog_Alert);
        activeDialog=new AlertDialog.Builder(context).setTitle(title).setView(view).setNegativeButton("取消",null)
            .setPositiveButton(action,(d,w)->confirmed.run()).create();
        activeDialog.show(); activeDialog.getButton(AlertDialog.BUTTON_POSITIVE).setTextColor(accent);
        return activeDialog;
    }
    private void confirmPair(String link) {
        if(S.pairing || isFinishing()) return;
        final Map<String,String> pair;
        try { pair=Protocol.pair(link); } catch(IllegalArgumentException e) { toast(e.getMessage()); return; }
        LinearLayout view=dialogContent();
        view.addView(label("中转地址",12,muted,false)); gap(view,6);
        view.addView(label(pair.get("relay"),15,textColor,true)); gap(view,14);
        view.addView(label("只连接你信任的电脑和中转。"+(S.device!=null?"确认后将替换当前手机连接。":""),14,muted,false));
        CheckBox remember=checkbox("记住此设备",false); view.addView(remember);
        view.addView(label("勾选：加密保存，下次打开自动连接。\n不勾选：仅本次使用，退出或进程结束后需重新扫码。",12,muted,false));
        showDialog("确认绑定电脑",view,"连接",()->claim(pair,remember.isChecked()));
    }
    private void claim(Map<String,String> pair,boolean remember) {
        if(S.pairing) return;
        S.pairing=true;
        String attempt=pair.get("relay")+"|"+pair.get("code");
        if(!attempt.equals(S.pendingCode)) { S.pendingCode=attempt; S.pendingToken=randomToken(); }
        String token=S.pendingToken; long generation=S.generation;
        toast("正在绑定电脑…");
        network.execute(()->{
            JSONObject device=null; Exception failure=null;
            try {
                JSONObject result=Api.relay(pair.get("relay"),"/v1/pair/claim","POST",
                    new JSONObject().put("pair_code",pair.get("code")).put("read_token",token),"");
                if(!result.getString("device_id").matches("[a-f0-9-]{36}")) throw new Exception();
                device=new JSONObject().put("relay",pair.get("relay")).put("token",token).put("id",result.getString("device_id"));
            } catch(Exception e) { failure=e; }
            JSONObject result=device; Exception error=failure;
            handler.post(()->{
                S.pairing=false;
                if(isDestroyed()||generation!=S.generation) return;
                if(error!=null) { toast(Api.error(error)); return; }
                try {
                    if(remember) secureStore.save(result); else secureStore.clear();
                } catch(Exception e) { toast("无法加密保存，将仅在本次使用中保留连接"); secureStore.clear(); }
                S.device=result; S.status=null; S.remembered=remember;
                // Verify persistence before advertising a remembered connection.
                if(remember) try { S.remembered=secureStore.load()!=null; } catch(Exception e) { S.remembered=false; }
                S.generation++; S.nextPoll=0; S.connectionError=""; S.unauthorized=false;
                S.pendingCode=""; S.pendingToken=""; page=0; render(); poll(false);
            });
        });
    }
    private void forget() {
        LinearLayout view=dialogContent();
        view.addView(label("删除这部手机保存的连接信息。电脑仍可继续钓鱼；要撤销所有手机访问，请在电脑端点“解除手机绑定”。",14,muted,false));
        showDialog("忘记此设备？",view,"忘记",()->{
            secureStore.clear(); S.device=null; S.status=null; S.remembered=false; S.unauthorized=false;
            S.connectionError=""; S.generation++; S.pendingCode=""; S.pendingToken=""; render();
        });
    }
    private void poll(boolean manual) {
        if(S.device==null||S.polling||S.unauthorized) return;
        long now=SystemClock.elapsedRealtime();
        if(now<S.nextPoll) { if(manual) toast("为节省额度，"+((S.nextPoll-now)/1000+1)+" 秒后可再次刷新"); return; }
        S.polling=true; S.nextPoll=now+60000;
        JSONObject device=S.device; long generation=S.generation;
        network.execute(()->{
            JSONObject result=null; Exception failure=null;
            try { result=Api.relay(device.getString("relay"),"/v1/status","GET",null,device.getString("token")); }
            catch(Exception e) { failure=e; }
            JSONObject data=result; Exception error=failure;
            handler.post(()->{
                S.polling=false;
                if(isDestroyed()||generation!=S.generation) return;
                if(error==null) { S.status=data; S.fetchedAt=SystemClock.elapsedRealtime(); S.connectionError=""; }
                else { S.connectionError=Api.error(error); S.unauthorized=error instanceof Api.Failure && ((Api.Failure)error).status==401; }
                if(page==0) renderStatusOnly();
            });
        });
    }
    private void checkUpdate(boolean manual) {
        if(updateBusy) return;
        if(SystemClock.elapsedRealtime()-lastUpdateAttempt<60000 && lastUpdateAttempt!=0) { if(manual) toast("请稍后再检查更新"); return; }
        updateBusy=true; lastUpdateAttempt=SystemClock.elapsedRealtime(); updateMessage="正在检查手机端更新…";
        if(page==2) render();
        updateNetwork.execute(()->{
            JSONObject result=null; Exception failure=null;
            try { result=Api.update(); } catch(Exception e) { failure=e; }
            JSONObject release=result; Exception error=failure;
            handler.post(()->{
                if(isDestroyed()) return;
                updateBusy=false;
                if(error!=null) updateMessage="更新检查失败，可稍后重试或打开项目页面";
                else {
                    preferences.edit().putLong("update_checked_at",System.currentTimeMillis()).apply();
                    updateMessage=release==null?"暂未发现更新的手机端安装包":"发现新版本 v"+release.optString("version");
                }
                if(page==2) render();
                if(release!=null && (manual||!release.optString("version").equals(preferences.getString("notified_version","")))) {
                    // Avoid replacing a pairing/security confirmation with an automatic update prompt.
                    if(activeDialog!=null && activeDialog.isShowing() && !manual) { pendingUpdate=release; return; }
                    showUpdate(release);
                } else if(manual) toast(updateMessage);
            });
        });
    }
    private void showUpdate(JSONObject release) {
        LinearLayout view=dialogContent();
        view.addView(label("v"+BuildConfig.VERSION_NAME+"  →  v"+release.optString("version"),14,accent,true)); gap(view,12);
        ScrollView notes=new ScrollView(this);
        String body=release.optString("body").trim();
        TextView note=label(body.isEmpty()?"此版本未提供更新说明。":body,14,textColor,false);
        note.setTextIsSelectable(true); notes.addView(note);
        view.addView(notes,new LinearLayout.LayoutParams(-1,dp(230)));
        AlertDialog dialog=showDialog("发现新版本",view,"前往下载",()->openBrowser(release.optString("url")));
        dialog.getButton(AlertDialog.BUTTON_NEGATIVE).setText("稍后再说");
        dialog.setOnDismissListener(d->preferences.edit().putString("notified_version",release.optString("version")).apply());
    }
    private void probe(String input) {
        if(probeBusy) return;
        final String relay;
        try { relay=Protocol.relay(input); } catch(IllegalArgumentException e) { toast(e.getMessage()); return; }
        probeBusy=true; probeMessage="正在测试当前网络…";
        preferences.edit().putString("probe_relay",relay).apply(); if(page==2) render();
        network.execute(()->{
            String message;
            try {
                long started=SystemClock.elapsedRealtime();
                JSONObject result=Api.relay(relay,"/v1/info","GET",null,"");
                message=result.optInt("protocol")==1?"连接正常 · "+(SystemClock.elapsedRealtime()-started)+" ms（仅代表当前网络）":"地址可访问，但中转协议不兼容";
            } catch(Exception e) { message=Api.error(e); }
            final String outcome=message;
            handler.post(()->{ if(isDestroyed()) return; probeBusy=false; probeMessage=outcome; if(page==2) render(); });
        });
    }
    private void openBrowser(String url) {
        // Browser links are fixed repo URLs or validated numeric release tags, never arbitrary API fields.
        try { startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(url))); }
        catch(Exception e) { toast("未找到可打开链接的浏览器"); }
    }
    private void toast(String text) { Toast.makeText(this,text,Toast.LENGTH_LONG).show(); }
    private static long statusAge() {
        return S.status==null?Long.MAX_VALUE:Math.max(0,S.status.optLong("server_time")-S.status.optLong("received_at"))+
            (SystemClock.elapsedRealtime()-S.fetchedAt)/1000;
    }
    private static String randomToken() {
        byte[] bytes=new byte[32]; new SecureRandom().nextBytes(bytes); StringBuilder s=new StringBuilder();
        for(byte b:bytes) s.append(String.format(Locale.ROOT,"%02x",b&255)); return s.toString();
    }
    private static String time(long seconds) { return new SimpleDateFormat("MM-dd HH:mm:ss",Locale.getDefault()).format(new Date(seconds*1000)); }
    private static String stateName(String state) {
        return switch(state) {
            case "waiting_bite" -> "等待上钩"; case "ready_to_cast" -> "准备抛竿"; case "fish_hooked" -> "已经上钩";
            case "idle_recovery" -> "恢复钓鱼"; case "cleaning" -> "清理背包"; case "paused" -> "已暂停";
            case "stopped" -> "已停止"; case "unresponsive" -> "识别状态未更新"; case "idle" -> "等待启动";
            default -> "识别中";
        };
    }
    private static String reasonName(String reason) {
        return switch(reason) {
            case "manual" -> "手动停止"; case "inventory_full" -> "背包已满"; case "rod_required" -> "需要装备或检查鱼竿";
            case "retry_limit" -> "重试达到上限"; case "error" -> "助手报告异常，请查看电脑日志"; default -> "";
        };
    }
}
