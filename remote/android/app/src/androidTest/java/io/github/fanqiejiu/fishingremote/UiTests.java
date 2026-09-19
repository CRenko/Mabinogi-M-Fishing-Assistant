package io.github.fanqiejiu.fishingremote;

import android.app.AlertDialog;
import android.content.Context;
import android.graphics.Bitmap;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.CheckBox;
import androidx.test.core.app.ActivityScenario;
import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.json.JSONObject;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import java.io.File;
import java.io.FileOutputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

@RunWith(AndroidJUnit4.class)
public class UiTests {
    private static void set(Object owner,String name,Object value) throws Exception {
        Field field=owner.getClass().getDeclaredField(name); field.setAccessible(true); field.set(owner,value);
    }
    private static Object get(Object owner,String name) throws Exception {
        Field field=owner.getClass().getDeclaredField(name); field.setAccessible(true); return field.get(owner);
    }
    private static void invoke(Object owner,String name) throws Exception {
        Method method=owner.getClass().getDeclaredMethod(name); method.setAccessible(true); method.invoke(owner);
    }
    private static CheckBox findRemember(View root) {
        if(root instanceof CheckBox && ((CheckBox)root).getText().toString().equals("记住此设备")) return (CheckBox)root;
        if(root instanceof ViewGroup) for(int i=0;i<((ViewGroup)root).getChildCount();i++) {
            CheckBox result=findRemember(((ViewGroup)root).getChildAt(i)); if(result!=null) return result;
        }
        return null;
    }
    private void screenshot(String name) throws Exception {
        var instrumentation=InstrumentationRegistry.getInstrumentation();
        instrumentation.waitForIdleSync(); SystemClock.sleep(400);
        Bitmap image=instrumentation.getUiAutomation().takeScreenshot(); assertNotNull(image);
        File dir=new File(instrumentation.getTargetContext().getExternalFilesDir(null),"qa"); dir.mkdirs();
        try(FileOutputStream out=new FileOutputStream(new File(dir,name+".png"))) { image.compress(Bitmap.CompressFormat.PNG,100,out); }
        image.recycle();
    }
    @Test public void pairingConsentThemeNavigationAndUpdateDialog() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        assertTrue(BuildConfig.DEBUG); // Never erase a real release installation's state.
        context.getSharedPreferences("settings",Context.MODE_PRIVATE).edit().putBoolean("auto_update",false).putString("theme","day").commit();
        new SecureStore(context).clear();
        try(ActivityScenario<MainActivity> scenario=ActivityScenario.launch(MainActivity.class)) {
            screenshot("home-day");
            scenario.onActivity(activity->{try {
                set(activity,"page",2); invoke(activity,"render");
            } catch(Exception e) { throw new AssertionError(e); }});
            screenshot("settings-day");
            scenario.onActivity(activity->{try {
                context.getSharedPreferences("settings",0).edit().putString("theme","night").commit(); invoke(activity,"render");
            } catch(Exception e) { throw new AssertionError(e); }});
            screenshot("settings-night");
            scenario.onActivity(activity->{try {
                Method confirm=MainActivity.class.getDeclaredMethod("confirmPair",String.class); confirm.setAccessible(true);
                confirm.invoke(activity,"okfishing://pair?v=1&relay=https%3A%2F%2Frelay.example&code="+"a".repeat(48));
                AlertDialog dialog=(AlertDialog)get(activity,"activeDialog");
                CheckBox remember=findRemember(dialog.getWindow().getDecorView());
                assertNotNull(remember); assertFalse(remember.isChecked()); remember.performClick(); assertTrue(remember.isChecked());
                assertNull(new SecureStore(context).load()); // Scanning/ticking must not persist or contact a relay.
            } catch(Exception e) { throw new AssertionError(e); }});
            screenshot("pair-remember-night");
            scenario.onActivity(activity->{try {
                ((AlertDialog)get(activity,"activeDialog")).dismiss();
                Method update=MainActivity.class.getDeclaredMethod("showUpdate",JSONObject.class); update.setAccessible(true);
                update.invoke(activity,new JSONObject().put("version","0.2.0").put("body","1. 修复状态长时间不更新的提示。\n\n2. 优化设备配对和深色界面的排版。\n\n3. 改进断网后的重连提示。").put("url",Api.RELEASES));
                AlertDialog dialog=(AlertDialog)get(activity,"activeDialog"); assertTrue(dialog.isShowing());
                assertEquals("稍后再说",dialog.getButton(AlertDialog.BUTTON_NEGATIVE).getText());
            } catch(Exception e) { throw new AssertionError(e); }});
            screenshot("update-night");
            scenario.onActivity(activity->{try {
                ((AlertDialog)get(activity,"activeDialog")).dismiss();
                Field field=MainActivity.class.getDeclaredField("S"); field.setAccessible(true); Object session=field.get(null);
                long now=System.currentTimeMillis()/1000;
                set(session,"device",new JSONObject().put("id","test-computer").put("relay","https://relay.example").put("token","a".repeat(64)));
                set(session,"nextPoll",SystemClock.elapsedRealtime()+3600000);
                set(session,"fetchedAt",SystemClock.elapsedRealtime());
                set(session,"status",new JSONObject().put("server_time",now).put("received_at",now).put("stale",false)
                    .put("status",new JSONObject().put("state","waiting_bite").put("calibrated",true).put("strategy","fixed_delay").put("recognition","ok").put("version","0.6.4")));
                set(activity,"page",0); invoke(activity,"render");
            } catch(Exception e) { throw new AssertionError(e); }});
            screenshot("status-night");
        }
    }
    @Test public void keystoreRoundTripAndForget() throws Exception {
        Context context=InstrumentationRegistry.getInstrumentation().getTargetContext();
        SecureStore store=new SecureStore(context);
        JSONObject data=new JSONObject().put("relay","https://relay.example").put("token","f".repeat(64)).put("id","test");
        store.save(data); assertEquals(data.toString(),store.load().toString());
        byte[] raw=java.nio.file.Files.readAllBytes(new File(context.getNoBackupFilesDir(),"device.enc").toPath());
        assertFalse(new String(raw,java.nio.charset.StandardCharsets.UTF_8).contains("f".repeat(64)));
        store.clear(); assertNull(store.load());
    }
}
