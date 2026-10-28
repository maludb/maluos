# Action Manifest — Phase 1

Status: **draft for Phase 1 sign-off** · 2026-09-13
The registry the command bar (chat-actions) and the actions MCP server resolve against. A screen or action missing here is unreachable by voice — treat as unfinished design. Every state-changing endpoint enforces `require_post()` + `verify_csrf()` + authorization + `log_activity()` (php-patterns). Web root is `/var/www/html`; endpoints below are paths under it.

Confirmation policy (locked): **creates/updates execute immediately with an Undo**; **destructive actions confirm first** (`hx-confirm`). Undo resolves the last action from the conversation + activity log.

---

## Screen registry

`navigate(screen, params)` resolves `screen` to a canonical URL; `params` map to the query string (GET controllers pre-fill from them). Never `hx-push-url="true"` — the explicit URL below is pushed.

| Screen id | Canonical URL | When the user wants… |
|---|---|---|
| `dashboard` | `/` | their home overview: next exam, this week's plan, replies waiting, cert banner |
| `calendar` | `/calendar` | to see the community calendar (exams + events); params: `month`, `exam`, `kind` |
| `attempts-list` | `/attempts/` | to see/manage their exams (attempts) |
| `attempt-add` | `/attempts/new` | to add an exam they're taking/considering; params: `exam` |
| `attempt-edit` | `/attempts/{id}/edit` | to edit/reschedule an attempt |
| `events-list` | `/events/` | to browse community events |
| `event-add` | `/events/new` | to schedule an event; params: `kind`, `exam`, `starts_at` |
| `event-edit` | `/events/{id}/edit` | to edit an event they host |
| `event-view` | `/events/{id}` | to see an event and its RSVPs |
| `plans-list` | `/plans/` | to browse study plans; params: `exam`, `from_passers` |
| `plan-add` | `/plans/new` | to create a study plan; params: `exam`, `attempt` |
| `plan-edit` | `/plans/{id}/edit` | to edit their plan |
| `plan-view` | `/plans/{id}` | to read a plan, its items and comments |
| `study-log` | `/study-log/` | to log/review study time; params: `exam` |
| `issues-list` | `/issues/` | to browse/search issues; params: `exam`, `domain`, `status`, `q` |
| `issue-add` | `/issues/new` | to post an issue; params: `exam`, `domain` |
| `issue-view` | `/issues/{id}` | to read an issue and its replies |
| `issue-edit` | `/issues/{id}/edit` | to edit their issue |
| `resources-list` | `/resources/` | to browse resources; params: `exam`, `domain`, `type`, `sort` |
| `resource-add` | `/resources/new` | to submit a resource; params: `exam`, `domain` |
| `resource-view` | `/resources/{id}` | to see a resource's details/endorsements |
| `members-list` | `/members/` | to browse the member directory; params: `exam`, `certified_in` |
| `member-view` | `/members/{id}` | to see a member's profile |
| `org-invitations` | `/organizer/invitations` | (organizer) to send/manage invitations |
| `org-exams` | `/organizer/exams` | (organizer) to manage the exam catalog + retake policy |
| `exam-edit` | `/organizer/exams/{id}/edit` | (organizer) to edit an exam and its domains |
| `org-health` | `/organizer/health` | (organizer) at-risk, pass rates, expiring certs, activity, unanswered |
| `ask` | `/ask` | to ask the assistant anything (full conversation) |
| `settings` | `/settings` | profile, timezone, notifications; params: `section` (profile/notifications/security/tokens/calendar) |
| `settings-2fa` | `/settings/2fa` | to enroll/manage authenticator 2FA |
| `login` | `/login` | to sign in (full navigation, not voice-routed) |
| `register` | `/register` | to accept an invite and register |

`navigate` fails usefully: unknown screen → closest registry matches with descriptions.

---

## Action registry

Params in **bold** are required. Every action logs the listed activity event. Endpoints are POST unless noted; deletes use DELETE.

### Exam attempts
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `attempt_create` | `/attempts/save.php` | **exam**, kind, status, exam_date, start_time, delivery | delete created attempt | — | `attempt.create` |
| `attempt_reschedule` | `/attempts/save.php` | **id**, **exam_date**, start_time | restore prior date | — | `attempt.reschedule` |
| `attempt_set_status` | `/attempts/status.php` | **id**, **status** | restore prior status | — | `attempt.status_change` |
| `attempt_record_result` | `/attempts/result.php` | **id**, **result** (passed/not_passed) | revert to prior status, clear cert dates | — | `attempt.record_result` |
| `attempt_share_result` | `/attempts/share.php` | **id**, **shared** (bool) | toggle back | — | `attempt.share_result` |
| `attempt_set_calendar_visibility` | `/attempts/visibility.php` | **id**, **visible** (bool) | toggle back | — | `attempt.hide_from_calendar` |
| `attempt_start_renewal` | `/attempts/renew.php` | **id** (passed attempt) | delete created renewal | — | `attempt.create` (kind=renewal) |
| `attempt_delete` | `/attempts/delete.php` | **id** | — (irreversible) | ✔ | `attempt.delete` |

*As-built:* attempts CRUD is POST (not DELETE verb) per the shell's HTMX wiring; `attempt-add`/`attempt-edit` served at `/attempts/form.php[?id={id}]` until mod_rewrite. Calendar refreshes via `HX-Target: calendar-region`. Built & verified live.

### Events & RSVPs
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `event_create` | `/events/save.php` | **kind**, **title**, **starts_at**, ends_at, is_online, meeting_url, location, exam, domain, capacity | delete created event | — | `event.create` |
| `event_update` | `/events/save.php` | **id**, … | restore prior values | — | `event.update` |
| `event_duplicate` | `/events/duplicate.php` | **id**, **starts_at** | delete created copy | — | `event.create` |
| `event_cancel` | `/events/cancel.php` | **id**, reason | set status back to scheduled | ✔ (notifies attendees) | `event.cancel` |
| `rsvp_set` | `/events/rsvp.php` | **event_id**, **response** (going/maybe/not_going) | restore prior response | — | `rsvp.set` |

### Study plans & items
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `plan_create` | `/plans/save.php` | **title**, **exam**, attempt, approach, visibility | delete created plan | — | `plan.create` |
| `plan_update` | `/plans/save.php` | **id**, … | restore prior values | — | `plan.update` |
| `plan_set_visibility` | `/plans/visibility.php` | **id**, **visibility** | toggle back | — | `plan.visibility_change` |
| `plan_archive` | `/plans/archive.php` | **id**, **archived** (bool) | toggle back | — | `plan.archive` |
| `plan_copy` | `/plans/copy.php` | **id**, target_attempt | delete created copy | — | `plan.copy` |
| `plan_item_add` | `/plans/items/save.php` | **plan_id**, **title**, domain, due_date, resource_id, notes | delete created item | — | `plan_item.create` |
| `plan_item_update` | `/plans/items/save.php` | **id**, … | restore prior values | — | `plan_item.update` |
| `plan_item_complete` | `/plans/items/complete.php` | **id**, **done** (bool) | toggle back | — | `plan_item.complete`/`reopen` |
| `plan_item_delete` | `/plans/items/delete.php` (DELETE) | **id** | — | ✔ | `plan_item.delete` |
| `plan_comment_add` | `/plans/comment.php` | **plan_id**, **body** | delete created comment | — | `plan_comment.create` |

### Study log
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `session_log` | `/study-log/save.php` | **minutes**, domain, exam, studied_on, confidence, resource_id, note | delete created session | — | `session.log` |
| `session_update` | `/study-log/save.php` | **id**, … | restore prior values | — | `session.update` |
| `session_delete` | `/study-log/delete.php` (DELETE) | **id** | — | ✔ | `session.delete` |

### Issues & replies
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `issue_create` | `/issues/save.php` | **title**, **body**, exam, domain | delete created issue | — | `issue.create` |
| `issue_update` | `/issues/save.php` | **id**, … | restore prior values | — | `issue.update` |
| `issue_resolve` | `/issues/resolve.php` | **id**, **resolved** (bool) | toggle back | — | `issue.resolve`/`reopen` |
| `reply_create` | `/issues/reply.php` | **issue_id**, **body**, resource_id | delete created reply | — | `reply.create` |
| `reply_accept` | `/issues/accept.php` | **issue_id**, **reply_id** | clear accepted reply | — | `reply.accept` |
| `issue_hide` † | `/issues/hide.php` | **id**, reason | unhide | ✔ | `issue.hide` |
| `reply_hide` † | `/issues/reply-hide.php` | **id**, reason | unhide | ✔ | `reply.hide` |

### Resources
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `resource_create` | `/resources/save.php` | **title**, **url**, **type**, description, exams[], domains[] | delete created resource | — | `resource.create` |
| `resource_update` | `/resources/save.php` | **id**, … | restore prior values | — | `resource.update` |
| `resource_endorse` | `/resources/endorse.php` | **id**, **on** (bool) | toggle back | — | `resource.endorse`/`unendorse` |
| `resource_hide` † | `/resources/hide.php` | **id**, reason | unhide | ✔ | `resource.hide` |

### Organizer — invitations
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `invite_send` † | `/organizer/invitations/save.php` | **email**, role, message | revoke the invite | — | `invite.send` |
| `invite_resend` † | `/organizer/invitations/resend.php` | **id** | — (email already sent) | — | `invite.resend` |
| `invite_revoke` † | `/organizer/invitations/revoke.php` | **id** | re-issue invite | ✔ | `invite.revoke` |

### Organizer — exam catalog
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `exam_create` † | `/organizer/exams/save.php` | **code**, **name**, … | delete created exam | — | `exam.create` |
| `exam_update` † | `/organizer/exams/save.php` | **id**, … | restore prior values | — | `exam.update` |
| `domain_save` † | `/organizer/exams/domain-save.php` | **exam_id**, **name**, **weight**, sort_order, id? | delete/restore | — | `domain.create`/`update` |
| `domain_delete` † | `/organizer/exams/domain-delete.php` | **exam_id**, **id** | — | ✔ | `domain.delete` |
| `domain_reorder` † | `/organizer/exams/domain-reorder.php` | **exam_id**, **id**, **dir** (up/down) | reorder back | — | `domain.reorder` |
| `exam_delete` † | `/organizer/exams/delete.php` | **id** | — (fails if in use) | ✔ | `exam.delete` |
| `retake_policy_update` † | `/organizer/exams/policy.php` | wait_days (csv), max_attempts_per_12mo, study_buddy_window_days, at_risk_no_study_days | restore prior values | — | `settings.update` |

*As-built URL note:* the `exam-add`/`exam-edit` screens are served at `/organizer/exams/form.php` and `/organizer/exams/form.php?id={id}` until `mod_rewrite` is enabled (then the canonical `/new` and `/{id}/edit` from the screen registry apply). See `docs/build-specs/exam-catalog.md`.

### Settings & tokens
| Action | Endpoint | Params | Undo | Confirm | Log |
|---|---|---|---|---|---|
| `profile_update` | `/settings/profile.php` | display_name, timezone, bio, organization | restore prior values | — | `member.update` |
| `notifications_update` | `/settings/notifications.php` | notify_reply, notify_event, notify_exam, notify_digest | restore prior values | — | `member.update` |
| `notification_mark_read` | `/notifications/read.php` | **id** (or all) | mark unread | — | (screen action) |
| `totp_enable` | `/settings/2fa/enable.php` | **code** (confirms enrollment) | disable 2FA | — | `auth.2fa_enrolled` |
| `totp_disable` | `/settings/2fa/disable.php` | **code** | — | ✔ | `auth.2fa_disabled` |
| `mcp_token_create` | `/settings/tokens/create.php` | **label** | revoke token | — | `token.create` |
| `mcp_token_revoke` | `/settings/tokens/revoke.php` | **id** | — | ✔ | `token.revoke` |
| `calendar_feed_create` | `/settings/calendar-feed/create.php` | — | revoke feed | — | `token.create` |
| `calendar_feed_revoke` | `/settings/calendar-feed/revoke.php` | **id** | — | ✔ | `token.revoke` |

† organizer-only (authorization enforced in the endpoint; the actions server relays the caller's role via the signed action token).

---

## Assistant / navigation
| Action | Contract |
|---|---|
| `navigate` | Input `screen` (registry id) + `params`. Validates against the registry, returns `{status:"success", navigate:{path, target:"#page-content"}}`; PHP handler emits `HX-Location`. At most one navigation per message; terminal (confirm in one sentence, end turn). |
| `undo_last` | Resolves the last action from the conversation + activity log; applies the inverse defined above. |

Data actions return a reply bubble + `HX-Trigger: {entity}Changed` so listening screen regions refresh (php-patterns Pattern D); the assistant never targets screen markup directly.

## Voice utterance coverage (plan §4 examples)
"move my CCAR-F exam to October 25th" → `attempt_reschedule` · "I passed" → `attempt_record_result` · "log 45 minutes on tool design and MCP today confidence 3" → `session_log` · "mark week two done" → `plan_item_complete` · "copy Priya's plan" → `plan_copy` · "post an issue…" → `issue_create` · "schedule a CCDV-F study group next Tuesday 7pm" → `event_create` · "RSVP yes to Thursday's study group" → `rsvp_set` · "add this link to resources for context management" → `resource_create` · "take me to November on the calendar" → `navigate(calendar, {month})` · "invite jane@example.com" → `invite_send`.
