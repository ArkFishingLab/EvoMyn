#pragma once

#include <functional>
#include <string>

namespace round_voice {
inline constexpr size_t kPairingJsonLimit = 16374;
inline constexpr size_t kPairingCaLimit = 12000;
inline constexpr int kPairingSchema = 1;

struct PairingConfig {
    std::string base_url, ca, token, device_id;
};

enum class PairingRead { Absent, Found, Error };
class PairingStore {
public:
    virtual ~PairingStore() = default;
    virtual PairingRead Read(std::string& blob) = 0;
    // One atomic blob. Never erase existing storage to recover from an error.
    virtual bool Commit(const std::string& blob) = 0;
};

// Owned by the physical console task after Boot; never exposed through MCP.
class RoundPairing {
public:
    using CertificateValidator = std::function<bool(const std::string&)>;
    RoundPairing(PairingStore& store, CertificateValidator certificate)
        : store_(store), certificate_(std::move(certificate)) {}
    bool Boot(const PairingConfig& legacy);
    bool Configured() const { return configured_; }
    const PairingConfig& Config() const { return config_; }
    // Empty means a valid non-pairing command for the application callback.
    // begin atomically excludes queued/running OTA and a ready OTA image.
    // finish receives true after any write attempt: restart before further OTA.
    std::string Control(const std::string& raw, const std::function<bool()>& begin,
                        const std::function<void(bool)>& finish);

private:
    PairingStore& store_;
    CertificateValidator certificate_;
    PairingConfig config_;
    bool configured_ = false;
    bool Valid(const PairingConfig& config) const;
    bool Decode(const std::string& blob, PairingConfig& config) const;
    bool Save(const PairingConfig& config);
};

#ifdef ESP_PLATFORM
class NvsPairingStore final : public PairingStore {
public:
    PairingRead Read(std::string& blob) override;
    bool Commit(const std::string& blob) override;
};
bool ValidatePairingCertificate(const std::string& pem);
#endif
}  // namespace round_voice
