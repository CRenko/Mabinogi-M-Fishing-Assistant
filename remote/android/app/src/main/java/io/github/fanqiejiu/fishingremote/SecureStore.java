package io.github.fanqiejiu.fishingremote;

import android.content.Context;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.AtomicFile;
import android.util.Base64;
import org.json.JSONObject;
import java.io.File;
import java.io.FileOutputStream;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;

final class SecureStore {
    private static final String ALIAS="ok-fishing-device";
    private final AtomicFile file;
    SecureStore(Context context) { file=new AtomicFile(new File(context.getNoBackupFilesDir(),"device.enc")); }
    private SecretKey key() throws Exception {
        KeyStore store=KeyStore.getInstance("AndroidKeyStore"); store.load(null);
        if (!store.containsAlias(ALIAS)) {
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());
            generator.generateKey();
        }
        return (SecretKey)store.getKey(ALIAS,null);
    }
    synchronized void save(JSONObject device) throws Exception {
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE,key());
        JSONObject wrapper=new JSONObject().put("iv",Base64.encodeToString(cipher.getIV(),Base64.NO_WRAP))
            .put("data",Base64.encodeToString(cipher.doFinal(device.toString().getBytes(StandardCharsets.UTF_8)),Base64.NO_WRAP));
        FileOutputStream out=null;
        try { out=file.startWrite(); out.write(wrapper.toString().getBytes(StandardCharsets.UTF_8)); file.finishWrite(out); }
        catch(Exception e) { if(out!=null) file.failWrite(out); throw e; }
    }
    synchronized JSONObject load() throws Exception {
        if(!file.getBaseFile().exists()) return null;
        if(file.getBaseFile().length()>16384) throw new Exception("invalid storage");
        JSONObject wrapper=new JSONObject(new String(file.readFully(),StandardCharsets.UTF_8));
        Cipher cipher=Cipher.getInstance("AES/GCM/NoPadding");
        cipher.init(Cipher.DECRYPT_MODE,key(),new GCMParameterSpec(128,Base64.decode(wrapper.getString("iv"),Base64.NO_WRAP)));
        JSONObject result=new JSONObject(new String(cipher.doFinal(Base64.decode(wrapper.getString("data"),Base64.NO_WRAP)),StandardCharsets.UTF_8));
        Protocol.relay(result.getString("relay"));
        if(!result.getString("token").matches("[a-f0-9]{64}")) throw new Exception("invalid token");
        return result;
    }
    synchronized void clear() { file.delete(); }
}
