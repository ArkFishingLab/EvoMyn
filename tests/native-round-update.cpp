#include "round_update_policy.h"
#include <cassert>
#include <string>

using namespace round_voice;

int main() {
  RoundUpdateManifest manifest{"round-voice-175c",
                               "2.5.4",
                               std::string(64, 'a'),
                               3355443,
                               "/updates/firmware/" + std::string(64, 'a') +
                                   ".bin",
                               "离线提醒与在线升级",
                               "v2/32m",
                               "xiaozhi"};
  assert(ValidateRoundUpdate(manifest, "2.5.3", 0x400000).empty());
  assert(!ValidateRoundUpdate(manifest, "2.5.4", 0x400000).empty());
  assert(!ValidateRoundUpdate(manifest, "2.5.5", 0x400000).empty());
  assert(!ValidateRoundUpdate(manifest, "2.5.3", 0x200000).empty());
  auto changed = manifest;
  changed.version = "2.5.30";
  assert(ValidateRoundUpdate(changed, "2.5.4", 0x400000).empty());
  for (const auto &bad : {"2.5", "2.5.4\n", "2.5.4-beta", "2.-1.4", "2.05.4",
                          "2.5.4294967296", "2.5.4.0", "", "2.5.+4"}) {
    changed = manifest;
    changed.version = bad;
    assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  }
  changed = manifest;
  changed.board = "other-board";
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  changed = manifest;
  changed.partition = "v2/16m";
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  changed = manifest;
  changed.project = "foreign";
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  for (auto size : {0U, 255U, 0x400001U}) {
    changed = manifest;
    changed.size = size;
    assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  }
  for (const auto &bad :
       {"http://192.0.2.10/image.bin", "https://evil/image.bin", "//evil/a",
        "/updates/firmware/../x.bin",
        "/updates/firmware/aaaaaaaa.bin?token=x"}) {
    changed = manifest;
    changed.url = bad;
    assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  }
  changed = manifest;
  changed.sha256[10] = 'A';
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  changed = manifest;
  changed.notes.assign(2049, 'x');
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  changed = manifest;
  changed.notes = std::string("\xc0\xaf", 2);
  assert(!ValidateRoundUpdate(changed, "2.5.3", 0x400000).empty());
  assert(ValidRoundUpdateBase("https://192.0.2.10:18773"));
  assert(ValidRoundUpdateBase("https://archive.local:18773"));
  for (const auto &bad :
       {"http://192.0.2.10", "https://user@host", "https://host/x",
        "https://host?x", "https://host#x", "https://host:0",
        "https://host:65536", "https://host:abc", "https://host\r\nX:x",
        "https://", "https://host/", "https://-host", "https://host..local"})
    assert(!ValidRoundUpdateBase(bad));
  RoundUpdateBoardMarker marker;
  assert(!marker.found());
  marker.Feed("prefixROUND-VOICE-", 18);
  const std::string remainder = "175C:v2/32m:OTA1suffix";
  marker.Feed(remainder.data(), remainder.size());
  assert(marker.found());
  RoundUpdateBoardMarker foreign;
  const std::string wrong = "ROUND-VOICE-OTHER:v2/32m:OTA1";
  foreign.Feed(wrong.data(), wrong.size());
  assert(!foreign.found());
}
