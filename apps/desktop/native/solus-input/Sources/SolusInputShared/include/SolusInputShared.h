// Shared by the agent (Swift, solus-input) and its only client, Solus.app main's
// native module (apps/desktop/native/solus-input-xpc, Objective-C++): the XPC
// interface and the signing constants, defined once (ADR-041 amendment
// 2026-10-28; docs/architecture/sol-drive.md §2.1).
#ifndef SOLUS_INPUT_SHARED_H
#define SOLUS_INPUT_SHARED_H

#import <Foundation/Foundation.h>

/// Replaced by a human with Solus's Apple team ID. While it is the placeholder
/// every code requirement fails: the agent exits at start, the listener admits
/// nobody and the native module refuses to connect (release fails closed).
#define SOLUS_TEAM_ID "SOLUS_TEAM_ID_PLACEHOLDER"
#define SOLUS_TEAM_ID_PLACEHOLDER "SOLUS_TEAM_ID_PLACEHOLDER"

#define SOLUS_AGENT_SERVICE "com.solusforge.solus.input.agent"
#define SOLUS_APP_IDENTIFIER "com.solusforge.solus"
#define SOLUS_HELPER_IDENTIFIER "com.solusforge.solus.input"

/// Developer ID: Apple anchor, the Developer ID intermediate (...6.2.6) and the
/// Developer ID Application leaf (...6.1.13), pinned to team (%s) then identifier (%s).
// One literal on one line: Swift imports single string-literal macros only.
// clang-format off
#define SOLUS_REQUIREMENT_FORMAT "anchor apple generic and certificate 1[field.1.2.840.113635.100.6.2.6] and certificate leaf[field.1.2.840.113635.100.6.1.13] and certificate leaf[subject.OU] = \"%s\" and identifier \"%s\""
// clang-format on

/// Requests are one JSON object of at most this many bytes.
#define SOLUS_AGENT_MAX_REQUEST_BYTES 65536

/// The agent's exported interface. `handle` replies with one JSON object;
/// `cancel` stops the request running for this connection before its next event.
NS_ASSUME_NONNULL_BEGIN
@protocol SolusInputAgent
- (void)handle:(NSData *)request reply:(void (^)(NSData *reply))reply;
- (void)cancel;
@end
NS_ASSUME_NONNULL_END

#endif
