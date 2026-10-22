#include "round_update_wire.h"
#include <cassert>
#include <string>

using namespace round_voice;

int main() {
  const std::string json =
      R"({"board":"round-voice-175c","version":"2.5.4","sha256":")" +
      std::string(64, 'a') + R"(","size":3355443,"url":"/updates/firmware/)" +
      std::string(64, 'a') +
      R"(.bin","notes":"离线提醒\n在线升级","partition":"v2/32m","project":"xiaozhi"})";
  RoundUpdateManifest manifest;
  assert(ParseRoundUpdateManifest(json, manifest).empty());
  assert(manifest.notes == "离线提醒\n在线升级");
  assert(manifest.size == 3355443);
  assert(ValidateRoundUpdate(manifest, "2.5.3", 0x400000).empty());
  for (const auto &bad :
       {"", "null", "[]", "{}", "{", "{\"size\":1e100}",
        "{\"notes\":\"bad\\u0000text\"}", "{\"notes\":{\"deep\":{}}}"})
    assert(!ParseRoundUpdateManifest(bad, manifest).empty());
  auto changed = json;
  changed.insert(1, "\"size\":1,");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
  changed = json;
  changed.insert(1, "\"unexpected\":1,");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
  changed = json;
  changed.replace(changed.find("3355443"), 7, "3355443.5");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
  changed = json;
  changed.replace(changed.find("3355443"), 7, "4294967296");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
  changed = json;
  changed.replace(changed.find("3355443"), 7, "-1");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
  assert(!ParseRoundUpdateManifest(json + "garbage", manifest).empty());
  assert(!ParseRoundUpdateManifest(json + std::string("\0data", 5), manifest)
              .empty());
  assert(!ParseRoundUpdateManifest(std::string(8193, ' '), manifest).empty());
  assert(ParseRoundUpdateManifest(json + " \n\t", manifest).empty());
  assert(ParseRoundUpdateManifest(json + "\r\n", manifest).empty());
  changed = json;
  changed.replace(changed.find("\\n"), 2, "\n");
  assert(!ParseRoundUpdateManifest(changed, manifest).empty());
}
