#include <cassert>
#include "archive_ack.h"

int main() {
    using round_voice::ArchiveAcknowledged;
    assert(ArchiveAcknowledged("{\"ok\":true,\"event_id\":\"e1\",\"record_id\":\"r1\"}", "e1"));
    assert(!ArchiveAcknowledged("{\"ok\":false,\"event_id\":\"e1\",\"record_id\":\"r1\"}", "e1"));
    assert(!ArchiveAcknowledged("{\"ok\":true,\"event_id\":\"e2\",\"record_id\":\"r1\"}", "e1"));
    assert(!ArchiveAcknowledged("{\"ok\":true,\"event_id\":\"e1\"}", "e1"));
    assert(!ArchiveAcknowledged("{\"ok\":true,\"ok\":false,\"event_id\":\"e1\",\"record_id\":\"r1\"}", "e1"));
    assert(!ArchiveAcknowledged("{\"ok\":true,\"event_id\":\"e1\",\"record_id\":\"r1\"}garbage", "e1"));
    assert(!ArchiveAcknowledged(std::string(2049, ' '), "e1"));
}
