#include <cJSON.h>
#include <cassert>
#include <string>
#include "round_console_wire.h"
#include "round_pairing.h"

using namespace round_voice;

struct MemoryStore : PairingStore {
    std::string blob;
    bool exists = false, read_error = false, commit_error = false, corrupt_readback = false;
    int writes = 0;
    PairingRead Read(std::string& value) override {
        if (read_error)
            return PairingRead::Error;
        if (!exists)
            return PairingRead::Absent;
        value = blob;
        return PairingRead::Found;
    }
    bool Commit(const std::string& value) override {
        ++writes;
        if (commit_error)
            return false;
        blob = corrupt_readback ? "{}" : value;
        exists = true;
        return true;
    }
};

const PairingConfig fixture{"https://fixture.invalid:8443", "fixture-certificate", "fixture-token",
                            "fixture-device"};
bool Certificate(const std::string& pem) { return pem == fixture.ca; }
std::string Command(const std::string& config) {
    return "{\"id\":7,\"op\":\"pairing_set\",\"config\":" + config + "}";
}
std::string ConfigJson(const PairingConfig& config) {
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "base_url", config.base_url.c_str());
    cJSON_AddStringToObject(root, "ca", config.ca.c_str());
    cJSON_AddStringToObject(root, "token", config.token.c_str());
    cJSON_AddStringToObject(root, "device_id", config.device_id.c_str());
    char* raw = cJSON_PrintUnformatted(root);
    std::string result(raw);
    cJSON_free(raw);
    cJSON_Delete(root);
    return result;
}
bool Flag(const std::string& reply, const char* field) {
    cJSON* root = cJSON_Parse(reply.c_str());
    assert(root);
    bool result = cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(root, field));
    cJSON_Delete(root);
    return result;
}

int main() {
    const auto config = ConfigJson(fixture);
    const auto command = Command(config);
    RoundConsoleLine wire;
    std::string framed;
    auto feed = [&](const std::string& bytes) {
        bool complete = false;
        for (char byte : bytes)
            complete = wire.Feed(byte, framed) || complete;
        return complete;
    };
    assert(feed("ROUND_CTL " + command + "\r\n"));
    assert(framed == "ROUND_CTL " + command + "\r");
    MemoryStore wire_store;
    RoundPairing wire_pairing(wire_store, Certificate);
    int wire_begin = 0;
    auto wire_acquire = [&] {
        ++wire_begin;
        return true;
    };
    assert(Flag(wire_pairing.Control(framed.substr(10), wire_acquire, [](bool) {}), "saved"));
    auto raw_cr = command;
    raw_cr.insert(raw_cr.find("fixture-token") + 7, 1, '\r');
    assert(feed("ROUND_CTL " + raw_cr + "\n"));
    assert(framed.find('\r') != std::string::npos);
    assert(!Flag(wire_pairing.Control(framed.substr(10), wire_acquire, [](bool) {}), "saved"));
    assert(wire_begin == 1 && wire_store.writes == 1);
    assert(!feed(std::string(16385, 'x') + "\n"));
    assert(feed("ROUND_CTL {\"op\":\"pairing_status\"}\n"));
    assert(Flag(wire_pairing.Control(framed.substr(10), wire_acquire, [](bool) {}), "configured"));
    MemoryStore store;
    RoundPairing pairing(store, Certificate);
    assert(!pairing.Boot({}));
    assert(!pairing.Configured());
    assert(store.writes == 0);
    assert(pairing.Boot(fixture));
    assert(pairing.Configured() && store.writes == 1);
    const auto original = store.blob;
    auto other = fixture;
    other.token = "other-token";
    RoundPairing restarted(store, Certificate);
    assert(restarted.Boot(other));
    assert(restarted.Config().token == fixture.token && store.writes == 1);
    assert(restarted.Boot({}) && store.writes == 1);

    int acquired = 0, released = 0;
    auto begin = [&] {
        ++acquired;
        return true;
    };
    auto finish = [&](bool) { ++released; };
    auto status = restarted.Control("{\"id\":7,\"op\":\"pairing_status\"}", begin, finish);
    assert(Flag(status, "ok") && Flag(status, "configured"));
    assert(status.find("schema") != std::string::npos);
    assert(status.find(fixture.token) == std::string::npos);
    assert(status.find("base_url") == std::string::npos && acquired == 0);
    assert(restarted.Control("{\"op\":\"status\"}", begin, finish).empty());
    auto busy = restarted.Control(command, [] { return false; }, finish);
    assert(!Flag(busy, "ok") && store.blob == original && released == 0);
    auto saved = restarted.Control(Command(ConfigJson(other)), begin, finish);
    assert(Flag(saved, "ok") && Flag(saved, "saved") && Flag(saved, "restart_required"));
    assert(saved.find(other.token) == std::string::npos && acquired == 1 && released == 1);
    RoundPairing next(store, Certificate);
    assert(next.Boot(fixture) && next.Config().token == other.token);

    for (auto bad : {"", "null", "[]", "{}", "{", "{\"base_url\":{\"deep\":{}}}",
                     "{\"base_url\":\"bad\\u0000hidden\"}"}) {
        assert(!Flag(next.Control(Command(bad), begin, finish), "ok"));
    }
    for (const char* field : {"base_url", "ca", "token", "device_id"}) {
        auto modified = fixture;
        if (std::string(field) == "base_url")
            modified.base_url = "http://fixture.invalid";
        if (std::string(field) == "ca")
            modified.ca = "not-a-certificate";
        if (std::string(field) == "token")
            modified.token = "bad\r\nHeader: value";
        if (std::string(field) == "device_id")
            modified.device_id = "bad device";
        assert(!Flag(next.Control(Command(ConfigJson(modified)), begin, finish), "ok"));
    }
    for (const auto& bad :
         {Command("{\"extra\":1," + config.substr(1)),
          Command("{\"token\":\"duplicate\"," + config.substr(1)), command + " trailing",
          command + std::string("\0", 1), "{\"id\":01," + command.substr(1),
          "{\"op\":\"pairing_set\",\"config\":" + config + ",}",
          "{\"id\":{\"token\":\"secret\"}," + command.substr(1),
          std::string("{\"op\":\"pairing_status\",\"extra\":1}"), std::string(16375, ' ')}) {
        assert(!Flag(next.Control(bad, begin, finish), "ok"));
    }
    for (int field = 0; field < 4; ++field) {
        auto modified = fixture;
        if (field == 0)
            modified.base_url = "https://" + std::string(281, 'a');
        if (field == 1)
            modified.ca = std::string(12001, 'a');
        if (field == 2)
            modified.token = std::string(257, 'a');
        if (field == 3)
            modified.device_id = std::string(129, 'a');
        assert(!Flag(next.Control(Command(ConfigJson(modified)), begin, finish), "ok"));
    }
    for (const auto& bad :
         {std::string("{}"), std::string(17000, 'x'), "{\"schema\":2," + config.substr(1),
          "{\"schema\":1,\"extra\":true," + config.substr(1)}) {
        MemoryStore invalid;
        invalid.exists = true;
        invalid.blob = bad;
        RoundPairing closed(invalid, Certificate);
        assert(!closed.Boot(fixture) && !closed.Configured());
        assert(!Flag(closed.Control(command, begin, finish), "saved"));
        assert(invalid.writes == 0 && invalid.blob == bad);
    }
    MemoryStore failed;
    failed.commit_error = true;
    RoundPairing failure(failed, Certificate);
    assert(!failure.Boot(fixture) && !failure.Configured() && !failed.exists);
    failed.commit_error = false;
    assert(failure.Boot(fixture));
    failed.commit_error = true;
    assert(!Flag(failure.Control(Command(ConfigJson(other)), begin, finish), "saved"));
    RoundPairing preserved(failed, Certificate);
    assert(preserved.Boot({}) && preserved.Config().token == fixture.token);
    MemoryStore unreadable;
    unreadable.read_error = true;
    RoundPairing unavailable(unreadable, Certificate);
    assert(!unavailable.Boot(fixture) && unreadable.writes == 0);
    MemoryStore broken;
    broken.corrupt_readback = true;
    RoundPairing unverified(broken, Certificate);
    assert(!unverified.Boot(fixture) && !unverified.Configured());
    assert(!Flag(unverified.Control(command, begin, finish), "saved"));
}
