#include "../xiaozhi-firmware/main/boards/round-voice-175c/wifi_model.h"
#include <cassert>
int main() {
    using namespace round_voice;
    assert(ValidWifiCredentials("home", "", WifiSecurity::Open));
    assert(!ValidWifiCredentials("home", "12345678", WifiSecurity::Open));
    assert(!ValidWifiCredentials("", "12345678", WifiSecurity::Personal));
    assert(ValidWifiCredentials(std::string(32, 's'), "12345678", WifiSecurity::Personal));
    assert(!ValidWifiCredentials(std::string(33, 's'), "12345678", WifiSecurity::Personal));
    assert(!ValidWifiCredentials("home", "1234567", WifiSecurity::Personal));
    assert(ValidWifiCredentials("home", std::string(63, 'p'), WifiSecurity::Personal));
    assert(ValidWifiCredentials("home", std::string(64, 'a'), WifiSecurity::Personal));
    assert(!ValidWifiCredentials("home", std::string(64, 'z'), WifiSecurity::Personal));
    assert(!ValidWifiCredentials("home", std::string(65, 'a'), WifiSecurity::Personal));
    assert(ValidWifiCredentials("sae", "short", WifiSecurity::Sae));
    assert(ValidWifiCredentials("sae", "short", SavedWifiSecurity("short")));
    assert(ValidWifiCredentials("saved-open", "", SavedWifiSecurity("")));
    assert(ValidWifiCredentials("saved-wpa2", "12345678", SavedWifiSecurity("12345678")));
    assert(!ValidWifiCredentials("enterprise", "12345678", WifiSecurity::Unsupported));
    assert(ValidWifiCredentials("manual-open", "", WifiSecurity::Unknown));
    for (auto rect : kWifiKeyboardRegions) {
        for (int x : {rect.x, rect.x + rect.w}) for (int y : {rect.y, rect.y + rect.h})
            assert((x-233)*(x-233)+(y-233)*(y-233) <= 219*219);
    }
}
