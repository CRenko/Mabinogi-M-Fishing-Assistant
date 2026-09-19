package io.github.fanqiejiu.fishingremote;
import org.junit.Test;
import static org.junit.Assert.*;

public class ProtocolTest {
    @Test public void acceptsHttpsPair() {
        var result=Protocol.pair("okfishing://pair?v=1&relay=https%3A%2F%2Frelay.example&code="+"a".repeat(48));
        assertEquals("https://relay.example",result.get("relay"));
    }
    @Test public void rejectsUnsafeOriginsAndDuplicateParameters() {
        for(String url:new String[]{"http://example.com","https://user:pass@example.com","https://example.com/path","https://example.com?token=1"}) {
            assertThrows(IllegalArgumentException.class,()->Protocol.relay(url));
        }
        assertThrows(IllegalArgumentException.class,()->Protocol.pair("okfishing://pair?v=1&v=1&relay=https%3A%2F%2Fx.com&code="+"a".repeat(48)));
    }
    @Test public void comparesNumericVersionsNotDesktopReleases() {
        assertTrue(Protocol.newer("0.10.0","0.9.1-dev"));
        assertFalse(Protocol.newer("0.1.0","0.1.0-dev"));
        assertFalse(Protocol.newer("0.1.0-beta","0.0.1"));
        assertFalse(Protocol.newer("999999999999999.1","0.1.0"));
    }
}
