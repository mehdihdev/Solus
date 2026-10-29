// Solus.app main's XPC client for the SOL drive agent (docs/architecture/sol-drive.md
// §2.1; ADR-041 amendment 2026-10-28). Exports
//   request(json: string, timeoutMs: number): Promise<string>
//   cancel(): void
// One NSXPCConnection to the agent's Mach service, required to satisfy the
// agent's code requirement (so nothing else can pose as it), re-created after
// invalidation. Each request has a deadline: on expiry it sends cancel() and
// rejects. XPC callbacks arrive on arbitrary queues; results reach JS through a
// per-request thread-safe function, settled exactly once.
#import <Foundation/Foundation.h>
#include <node_api.h>

#include <atomic>
#include <cmath>
#include <cstring>
#include <memory>
#include <string>

#import "SolusInputShared.h"

namespace {

constexpr double kMaxTimeoutMs = 600000;
constexpr size_t kTeamIdLength = 10;

/// Guards gConnection; every XPC call is issued from here.
dispatch_queue_t Queue() {
    static dispatch_queue_t queue = dispatch_queue_create("com.solusforge.solus.input-xpc", DISPATCH_QUEUE_SERIAL);
    return queue;
}

NSXPCConnection *gConnection = nil;

bool TeamIdIsReal(const char *team) {
    if (std::strcmp(team, SOLUS_TEAM_ID_PLACEHOLDER) == 0 || std::strlen(team) != kTeamIdLength) return false;
    for (const char *c = team; *c; ++c) {
        if (!((*c >= 'A' && *c <= 'Z') || (*c >= '0' && *c <= '9'))) return false;
    }
    return true;
}

/// The agent's requirement; nil while the team ID is the placeholder (fail closed).
NSString *AgentRequirement() {
    if (!TeamIdIsReal(SOLUS_TEAM_ID)) return nil;
    return [NSString stringWithFormat:@SOLUS_REQUIREMENT_FORMAT, SOLUS_TEAM_ID, SOLUS_HELPER_IDENTIFIER];
}

/// On Queue(): the live connection, created on first use and after invalidation.
NSXPCConnection *Connection() {
    if (gConnection) return gConnection;
    NSString *requirement = AgentRequirement();
    if (!requirement) return nil;
    NSXPCConnection *connection = [[NSXPCConnection alloc] initWithMachServiceName:@SOLUS_AGENT_SERVICE options:0];
    connection.remoteObjectInterface = [NSXPCInterface interfaceWithProtocol:@protocol(SolusInputAgent)];
    [connection setCodeSigningRequirement:requirement];
    __weak NSXPCConnection *weak = connection;
    connection.invalidationHandler = ^{
      dispatch_async(Queue(), ^{
        if (gConnection == weak) gConnection = nil;
      });
    };
    [connection resume];
    gConnection = connection;
    return connection;
}

struct Pending {
    napi_deferred deferred = nullptr;
    napi_threadsafe_function tsfn = nullptr;
    std::atomic<bool> settled{false};
};

struct Outcome {
    std::shared_ptr<Pending> pending;
    bool ok;
    std::string text;
};

/// On the JS thread: resolve or reject, then let the thread-safe function go.
void CallJs(napi_env env, napi_value, void *, void *data) {
    std::unique_ptr<Outcome> outcome(static_cast<Outcome *>(data));
    if (env) {
        napi_value text;
        napi_create_string_utf8(env, outcome->text.data(), outcome->text.size(), &text);
        if (outcome->ok) {
            napi_resolve_deferred(env, outcome->pending->deferred, text);
        } else {
            napi_value error;
            napi_create_error(env, nullptr, text, &error);
            napi_reject_deferred(env, outcome->pending->deferred, error);
        }
    }
    napi_release_threadsafe_function(outcome->pending->tsfn, napi_tsfn_release);
}

/// From any queue; only the first call for a request counts.
void Settle(const std::shared_ptr<Pending> &pending, bool ok, std::string text) {
    bool expected = false;
    if (!pending->settled.compare_exchange_strong(expected, true)) return;
    napi_call_threadsafe_function(pending->tsfn, new Outcome{pending, ok, std::move(text)}, napi_tsfn_blocking);
}

napi_value Throw(napi_env env, bool range, const char *message) {
    if (range) napi_throw_range_error(env, nullptr, message);
    else napi_throw_type_error(env, nullptr, message);
    return nullptr;
}

napi_value Rejected(napi_env env, napi_deferred deferred, napi_value promise, const char *message) {
    napi_value text, error;
    napi_create_string_utf8(env, message, NAPI_AUTO_LENGTH, &text);
    napi_create_error(env, nullptr, text, &error);
    napi_reject_deferred(env, deferred, error);
    return promise;
}

napi_value Request(napi_env env, napi_callback_info info) {
    size_t argc = 2;
    napi_value argv[2];
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
    napi_valuetype jsonType = napi_undefined, timeoutType = napi_undefined;
    if (argc >= 1) napi_typeof(env, argv[0], &jsonType);
    if (argc >= 2) napi_typeof(env, argv[1], &timeoutType);
    if (jsonType != napi_string || timeoutType != napi_number) {
        return Throw(env, false, "request(json: string, timeoutMs: number)");
    }
    double timeoutMs = 0;
    napi_get_value_double(env, argv[1], &timeoutMs);
    if (!std::isfinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > kMaxTimeoutMs) {
        return Throw(env, true, "timeoutMs must be > 0 and <= 600000");
    }
    size_t length = 0;
    napi_get_value_string_utf8(env, argv[0], nullptr, 0, &length);
    std::string json(length, '\0');
    napi_get_value_string_utf8(env, argv[0], json.data(), length + 1, &length);

    auto pending = std::make_shared<Pending>();
    napi_value promise;
    napi_create_promise(env, &pending->deferred, &promise);
    if (json.size() > SOLUS_AGENT_MAX_REQUEST_BYTES) return Rejected(env, pending->deferred, promise, "request exceeds 64 KiB");
    if (!AgentRequirement()) {
        return Rejected(env, pending->deferred, promise, "drive agent unavailable: the Solus team ID is not set");
    }

    napi_value name;
    napi_create_string_utf8(env, "solus-input-xpc.request", NAPI_AUTO_LENGTH, &name);
    if (napi_create_threadsafe_function(env, nullptr, nullptr, name, 0, 1, nullptr, nullptr, nullptr, CallJs,
                                        &pending->tsfn) != napi_ok) {
        return Rejected(env, pending->deferred, promise, "cannot schedule the request");
    }

    NSData *data = [NSData dataWithBytes:json.data() length:json.size()];
    int64_t deadline = static_cast<int64_t>(timeoutMs * NSEC_PER_MSEC);
    dispatch_async(Queue(), ^{
      NSXPCConnection *connection = Connection();
      if (!connection) return Settle(pending, false, "drive agent unavailable");
      id<SolusInputAgent> agent = [connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
        Settle(pending, false, std::string("drive agent error: ") + error.localizedDescription.UTF8String);
      }];
      [agent handle:data
              reply:^(NSData *reply) {
                NSString *text = [[NSString alloc] initWithData:reply encoding:NSUTF8StringEncoding];
                if (text) Settle(pending, true, text.UTF8String);
                else Settle(pending, false, "drive agent replied with invalid UTF-8");
              }];
      dispatch_after(dispatch_time(DISPATCH_TIME_NOW, deadline), Queue(), ^{
        if (pending->settled.load()) return;
        [[connection remoteObjectProxyWithErrorHandler:^(NSError *) {}] cancel];
        Settle(pending, false, "drive agent timed out");
      });
    });
    return promise;
}

napi_value Cancel(napi_env env, napi_callback_info) {
    dispatch_async(Queue(), ^{
      [[gConnection remoteObjectProxyWithErrorHandler:^(NSError *) {}] cancel];
    });
    napi_value undefined;
    napi_get_undefined(env, &undefined);
    return undefined;
}

napi_value Init(napi_env env, napi_value exports) {
    napi_property_descriptor properties[] = {
        {"request", nullptr, Request, nullptr, nullptr, nullptr, napi_enumerable, nullptr},
        {"cancel", nullptr, Cancel, nullptr, nullptr, nullptr, napi_enumerable, nullptr},
    };
    napi_define_properties(env, exports, 2, properties);
    return exports;
}

}  // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, Init)
