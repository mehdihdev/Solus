// Solus.app main's XPC client for the SOL drive agent (docs/architecture/sol-drive.md
// §2.1; ADR-041 amendment 2026-10-28). Exports
//   request(json: string, timeoutMs: number): { id: number, promise: Promise<string> }
//   cancel(id: number): void        — stops (or drops, if queued) that request only
//   checkOwnBundle(): Promise<boolean> — Solus.app's own bundle is intact, Solus-signed and hardened
// One NSXPCConnection to the agent's Mach service, required to satisfy the
// agent's code requirement (so nothing else can pose as it), re-created after
// invalidation. Each request gets an id; its deadline cancels only that id and
// rejects. A request the agent never answered is sent once more if the
// connection was interrupted (the agent exiting idle as it arrived) — only when
// it posts no input (trust, identify, capture); an `act` is never replayed. XPC
// callbacks arrive on arbitrary queues; results reach JS through a per-request
// thread-safe function, settled exactly once.
#import <Foundation/Foundation.h>
#import <Security/Security.h>
#include <node_api.h>

#include <atomic>
#include <cmath>
#include <cstring>
#include <memory>
#include <set>
#include <string>

#import "SolusInputShared.h"

namespace {

constexpr double kMaxTimeoutMs = 600000;
constexpr size_t kTeamIdLength = 10;
constexpr int64_t kMaxId = 9007199254740991;  // what JSON carries exactly

/// Guards gConnection, gInFlight and each request's retry flag; every XPC call is issued from here.
dispatch_queue_t Queue() {
    static dispatch_queue_t queue = dispatch_queue_create("com.solusforge.solus.input-xpc", DISPATCH_QUEUE_SERIAL);
    return queue;
}

NSXPCConnection *gConnection = nil;
std::set<int64_t> gInFlight;
std::atomic<int64_t> gNextId{1};

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

/// Solus.app's requirement, as the agent's listener checks it; nil while the placeholder.
NSString *AppRequirement() {
    if (!TeamIdIsReal(SOLUS_TEAM_ID)) return nil;
    return [NSString stringWithFormat:@SOLUS_REQUIREMENT_FORMAT SOLUS_APP_REQUIREMENT_SUFFIX, SOLUS_TEAM_ID,
                                      SOLUS_APP_IDENTIFIER, SOLUS_APP_VERSION_FLOOR];
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

/// On Queue(): tell the agent to stop or drop request `id` (nothing else).
void SendCancel(int64_t id) {
    [[gConnection remoteObjectProxyWithErrorHandler:^(NSError *) {}] cancel:static_cast<NSInteger>(id)];
}

struct Pending {
    napi_deferred deferred = nullptr;
    napi_threadsafe_function tsfn = nullptr;
    std::atomic<bool> settled{false};
    int64_t id = 0;
    NSData *data = nil;
    bool retryable = false;  // posts no input: may be sent again after an interruption
    bool retried = false;    // Queue() only
};

struct Outcome {
    std::shared_ptr<Pending> pending;
    bool ok;
    bool isBoolean;
    bool boolean;
    std::string text;
};

/// On the JS thread: resolve or reject, then let the thread-safe function go.
void CallJs(napi_env env, napi_value, void *, void *data) {
    std::unique_ptr<Outcome> outcome(static_cast<Outcome *>(data));
    if (env) {
        napi_value value;
        if (outcome->isBoolean) napi_get_boolean(env, outcome->boolean, &value);
        else napi_create_string_utf8(env, outcome->text.data(), outcome->text.size(), &value);
        if (outcome->ok) {
            napi_resolve_deferred(env, outcome->pending->deferred, value);
        } else {
            napi_value error;
            napi_create_error(env, nullptr, value, &error);
            napi_reject_deferred(env, outcome->pending->deferred, error);
        }
    }
    napi_release_threadsafe_function(outcome->pending->tsfn, napi_tsfn_release);
}

/// From any queue; only the first call for a request counts.
void Settle(const std::shared_ptr<Pending> &pending, Outcome *outcome) {
    std::unique_ptr<Outcome> owned(outcome);
    bool expected = false;
    if (!pending->settled.compare_exchange_strong(expected, true)) return;
    if (napi_call_threadsafe_function(pending->tsfn, owned.get(), napi_tsfn_blocking) == napi_ok) owned.release();
}

void SettleText(const std::shared_ptr<Pending> &pending, bool ok, std::string text) {
    Settle(pending, new Outcome{pending, ok, false, false, std::move(text)});
}

/// On Queue(): settle and forget the id.
void Finish(const std::shared_ptr<Pending> &pending, bool ok, std::string text) {
    gInFlight.erase(pending->id);
    SettleText(pending, ok, std::move(text));
}

std::string Describe(NSError *error) {
    NSString *text = error.localizedDescription;
    return std::string("drive agent error: ") + (text.UTF8String ? text.UTF8String : "unknown");
}

/// On Queue(): send (or re-send once after an interruption) and wire the reply.
void Send(const std::shared_ptr<Pending> &pending) {
    NSXPCConnection *connection = Connection();
    if (!connection) return Finish(pending, false, "drive agent unavailable");
    id<SolusInputAgent> agent = [connection remoteObjectProxyWithErrorHandler:^(NSError *error) {
      dispatch_async(Queue(), ^{
        if (pending->settled.load()) return;
        bool interrupted = [error.domain isEqualToString:NSCocoaErrorDomain] && error.code == NSXPCConnectionInterrupted;
        if (interrupted && pending->retryable && !pending->retried) {
            pending->retried = true;
            return Send(pending);
        }
        Finish(pending, false, Describe(error));
      });
    }];
    [agent handle:pending->data
            reply:^(NSData *reply) {
              NSString *text = [[NSString alloc] initWithData:reply encoding:NSUTF8StringEncoding];
              std::string body = text.UTF8String ? text.UTF8String : "";
              dispatch_async(Queue(), ^{
                if (text) Finish(pending, true, body);
                else Finish(pending, false, "drive agent replied with invalid UTF-8");
              });
            }];
}

napi_value Throw(napi_env env, bool range, const char *message) {
    if (range) napi_throw_range_error(env, nullptr, message);
    else napi_throw_type_error(env, nullptr, message);
    return nullptr;
}

/// `{ id, promise }` — what `request` returns.
napi_value Handle(napi_env env, int64_t id, napi_value promise) {
    napi_value handle, idValue;
    napi_create_object(env, &handle);
    napi_create_int64(env, id, &idValue);
    napi_set_named_property(env, handle, "id", idValue);
    napi_set_named_property(env, handle, "promise", promise);
    return handle;
}

/// Rejects before anything was dispatched, and lets the thread-safe function go
/// (an unreleased one would keep the event loop alive). Returns `result` as given.
napi_value Rejected(napi_env env, const std::shared_ptr<Pending> &pending, napi_value result, const char *message) {
    pending->settled.store(true);
    napi_value text, error;
    napi_create_string_utf8(env, message, NAPI_AUTO_LENGTH, &text);
    napi_create_error(env, nullptr, text, &error);
    napi_reject_deferred(env, pending->deferred, error);
    if (pending->tsfn) napi_release_threadsafe_function(pending->tsfn, napi_tsfn_release);
    return result;
}

/// A promise whose settlement can come from any queue.
napi_value MakePending(napi_env env, const char *name, std::shared_ptr<Pending> &pending, bool *ok) {
    pending = std::make_shared<Pending>();
    napi_value promise, resource;
    napi_create_promise(env, &pending->deferred, &promise);
    napi_create_string_utf8(env, name, NAPI_AUTO_LENGTH, &resource);
    *ok = napi_create_threadsafe_function(env, nullptr, nullptr, resource, 0, 1, nullptr, nullptr, nullptr, CallJs,
                                          &pending->tsfn) == napi_ok;
    return promise;
}

/// `json` with the module's id added; nil unless it is a JSON object that still
/// fits. `retryable` says whether it may be sent again (SolusInputRequestIsRetryable).
NSData *WithId(const std::string &json, int64_t requestId, bool *retryable) {
    NSData *raw = [NSData dataWithBytes:json.data() length:json.size()];
    id object = [NSJSONSerialization JSONObjectWithData:raw options:0 error:nil];
    if (![object isKindOfClass:[NSDictionary class]]) return nil;
    id op = object[@"op"];
    id argv = object[@"argv"];
    id command = [argv isKindOfClass:[NSArray class]] ? [argv firstObject] : nil;
    *retryable = [op isKindOfClass:[NSString class]] &&
                 SolusInputRequestIsRetryable(op, [command isKindOfClass:[NSString class]] ? command : nil);
    NSMutableDictionary *request = [object mutableCopy];
    request[@"id"] = @(requestId);
    NSData *data = [NSJSONSerialization dataWithJSONObject:request options:0 error:nil];
    return data.length <= SOLUS_AGENT_MAX_REQUEST_BYTES ? data : nil;
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

    std::shared_ptr<Pending> pending;
    bool scheduled = false;
    napi_value promise = MakePending(env, "solus-input-xpc.request", pending, &scheduled);
    int64_t id = gNextId.fetch_add(1);
    pending->id = id;
    napi_value handle = Handle(env, id, promise);
    if (json.size() > SOLUS_AGENT_MAX_REQUEST_BYTES) return Rejected(env, pending, handle, "request exceeds 64 KiB");
    if (id > kMaxId) return Rejected(env, pending, handle, "request ids exhausted");
    pending->data = WithId(json, id, &pending->retryable);
    if (!pending->data) return Rejected(env, pending, handle, "request must be a JSON object within 64 KiB");
    if (!AgentRequirement()) {
        return Rejected(env, pending, handle, "drive agent unavailable: the Solus team ID is not set");
    }
    if (!scheduled) return Rejected(env, pending, handle, "cannot schedule the request");

    int64_t deadline = static_cast<int64_t>(timeoutMs * NSEC_PER_MSEC);
    dispatch_async(Queue(), ^{
      gInFlight.insert(pending->id);
      Send(pending);
      dispatch_after(dispatch_time(DISPATCH_TIME_NOW, deadline), Queue(), ^{
        if (pending->settled.load()) return;
        SendCancel(pending->id);  // this request only: never another one running
        Finish(pending, false, "drive agent timed out");
      });
    });
    return handle;
}

napi_value Cancel(napi_env env, napi_callback_info info) {
    size_t argc = 1;
    napi_value argv[1];
    napi_get_cb_info(env, info, &argc, argv, nullptr, nullptr);
    napi_valuetype type = napi_undefined;
    if (argc >= 1) napi_typeof(env, argv[0], &type);
    double value = 0;
    if (type == napi_number) napi_get_value_double(env, argv[0], &value);
    if (type != napi_number || !std::isfinite(value) || value < 1 || value > kMaxId || std::floor(value) != value) {
        return Throw(env, false, "cancel(id): a request id from request()");
    }
    int64_t id = static_cast<int64_t>(value);
    dispatch_async(Queue(), ^{
      if (gInFlight.count(id)) SendCancel(id);  // only a request of ours still in flight
    });
    napi_value undefined;
    napi_get_undefined(env, &undefined);
    return undefined;
}

/// The running process itself: hardened runtime, valid, never debugged
/// (SolusInputCodeIsHardened, the predicate the agent applies to its clients).
bool RunningCodeIsHardened(SecCodeRef running) {
    CFDictionaryRef info = nullptr;
    if (SecCodeCopySigningInformation((SecStaticCodeRef)running, kSecCSDynamicInformation, &info) != errSecSuccess) {
        return false;
    }
    NSDictionary *values = (__bridge_transfer NSDictionary *)info;
    uint32_t flags = [values[(__bridge NSString *)kSecCodeInfoFlags] unsignedIntValue];
    uint32_t status = [values[(__bridge NSString *)kSecCodeInfoStatus] unsignedIntValue];
    return SolusInputCodeIsHardened(flags, status);
}

/// Static validity of the running app's whole bundle (nested code, strict, every
/// architecture) against Solus.app's requirement, and the running process
/// hardened. Off the JS thread.
bool OwnBundleIsSolus() {
    NSString *requirementText = AppRequirement();
    if (!requirementText) return false;
    SecCodeRef running = nullptr;
    SecStaticCodeRef bundle = nullptr;
    SecRequirementRef requirement = nullptr;
    bool valid = SecCodeCopySelf(kSecCSDefaultFlags, &running) == errSecSuccess &&
                 SecCodeCopyStaticCode(running, kSecCSDefaultFlags, &bundle) == errSecSuccess &&
                 SecRequirementCreateWithString((__bridge CFStringRef)requirementText, kSecCSDefaultFlags,
                                                &requirement) == errSecSuccess &&
                 SecStaticCodeCheckValidity(bundle,
                                            kSecCSCheckNestedCode | kSecCSStrictValidate | kSecCSCheckAllArchitectures,
                                            requirement) == errSecSuccess &&
                 RunningCodeIsHardened(running);
    if (requirement) CFRelease(requirement);
    if (bundle) CFRelease(bundle);
    if (running) CFRelease(running);
    return valid;
}

napi_value CheckOwnBundle(napi_env env, napi_callback_info) {
    std::shared_ptr<Pending> pending;
    bool scheduled = false;
    napi_value promise = MakePending(env, "solus-input-xpc.checkOwnBundle", pending, &scheduled);
    if (!scheduled) return Rejected(env, pending, promise, "cannot schedule the check");
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
      Settle(pending, new Outcome{pending, true, true, OwnBundleIsSolus(), ""});
    });
    return promise;
}

napi_value Init(napi_env env, napi_value exports) {
    napi_property_descriptor properties[] = {
        {"request", nullptr, Request, nullptr, nullptr, nullptr, napi_enumerable, nullptr},
        {"cancel", nullptr, Cancel, nullptr, nullptr, nullptr, napi_enumerable, nullptr},
        {"checkOwnBundle", nullptr, CheckOwnBundle, nullptr, nullptr, nullptr, napi_enumerable, nullptr},
    };
    napi_define_properties(env, exports, 3, properties);
    return exports;
}

}  // namespace

NAPI_MODULE(NODE_GYP_MODULE_NAME, Init)
