import type { Metadata } from "next";
import ActionForm from "@/components/kit/ActionForm";
import Link from "@/components/kit/Link";
import PageHeader from "@/components/kit/PageHeader";
import SubmitButton from "@/components/kit/SubmitButton";
import { renderScreen } from "@/lib/screen";
import { myChannels } from "@/lib/schemas/assistants";

export const metadata: Metadata = { title: "My channels" };

/**
 * Screen `my-channels` (db/156) — the channels that reach your personal assistant. Telegram: ask for a code
 * and send it to your assistant's bot. SMS: give your number, then enter the code texted to it. Email: give
 * your address, then enter the code mailed to it from your assistant's mailbox. Only a
 * linked account is heard; a message from anyone else is dropped. Replies come back on the channel you
 * last wrote from, else your preferred one. Data: GET /settings/channels.
 */
export default async function MyChannelsPage() {
  return renderScreen("/settings/channels", myChannels, (data) => {
    const endpoint = (c: string) => data.endpoints.find((e) => e.channel === c)?.address ?? null;
    const linked = data.identities.filter((i) => i.verified);
    // A code is on its way: the address it went to stays in the form (React clears a form once its action
    // succeeds, so the field is keyed on it and re-mounts filled) and the code box says where to look.
    const pending = (c: string) => data.identities.find((i) => !i.verified && i.channel === c)?.label ?? null;
    const pendingSms = pending("sms");
    const pendingEmail = pending("email");
    return (
      <>
        <PageHeader title="My channels" id="my-channels" crumbs={[{ label: "Settings", href: "/settings" }, { label: "Channels" }]} />
        <div className="main-content" data-screen="my-channels">
          {data.assistant === null ? (
            <p className="text-muted">You have no personal assistant yet, so there is nothing to reach. A super-admin assigns one.</p>
          ) : (
            <>
              <p className="text-muted fs-13">
                These reach <Link href="/assistant">{data.assistant.name}</Link>, your assistant. Only a linked account is heard. Changes you ask
                for by SMS or email are confirmed on Telegram or in the OS before anything is done, because a text or an email can be forged.
              </p>
              <div className="row">
                <div className="col-lg-6">
                  <div className="card" id="my-channels-linked">
                    <div className="card-header"><h5 className="card-title">Linked</h5></div>
                    <ul className="list-group list-group-flush">
                      {linked.length === 0 && <li className="list-group-item text-muted">Nothing linked yet.</li>}
                      {linked.map((i) => (
                        <li className="list-group-item d-flex flex-wrap align-items-center gap-2" key={i.id} id={`my-channel-${i.id}`}>
                          <span className="fw-semibold text-capitalize">{i.channel}</span><span className="text-muted">{i.label}</span>
                          {i.preferred && <span className="badge bg-soft-success text-success">replies come here</span>}
                          <span className="ms-auto d-flex gap-1">
                            {!i.preferred && (
                              <ActionForm path="/settings/channels/prefer.php">
                                <input type="hidden" name="identity" value={i.id} />
                                <SubmitButton className="btn btn-sm btn-light-brand">Prefer</SubmitButton>
                              </ActionForm>
                            )}
                            <ActionForm path="/settings/channels/remove.php" confirm={`Stop ${i.channel} ${i.label ?? ""} from reaching your assistant?`}>
                              <input type="hidden" name="identity" value={i.id} />
                              <SubmitButton className="btn btn-sm btn-light-brand text-danger">Remove</SubmitButton>
                            </ActionForm>
                          </span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
                <div className="col-lg-6">
                  <div className="card" id="my-channels-telegram">
                    <div className="card-header"><h5 className="card-title">Telegram</h5></div>
                    <div className="card-body">
                      {endpoint("telegram") === null ? <p className="text-muted mb-0">Your assistant has no Telegram bot yet.</p> : (
                        <ActionForm path="/settings/channels/link.php">
                          <input type="hidden" name="channel" value="telegram" />
                          <p className="fs-13">Get a code, then send it to <code>{endpoint("telegram")}</code> on Telegram within 15 minutes.</p>
                          <SubmitButton className="btn btn-primary" id="my-channels-telegram-code">Get a code</SubmitButton>
                        </ActionForm>
                      )}
                    </div>
                  </div>
                  <div className="card" id="my-channels-sms">
                    <div className="card-header"><h5 className="card-title">SMS</h5></div>
                    <div className="card-body">
                      {endpoint("sms") === null ? <p className="text-muted mb-0">Your assistant has no phone number yet.</p> : (
                        <>
                          <ActionForm path="/settings/channels/link.php" className="d-flex flex-wrap gap-2 align-items-center mb-3">
                            <input type="hidden" name="channel" value="sms" />
                            <input type="tel" name="address" className="form-control w-auto" placeholder="+15551234567" required
                                   key={pendingSms ?? "none"} defaultValue={pendingSms ?? ""}
                                   id="my-channels-sms-number" aria-label="Your phone number, with country code" />
                            <SubmitButton className="btn btn-primary" id="my-channels-sms-send">{pendingSms ? "Text a new code" : "Text me a code"}</SubmitButton>
                          </ActionForm>
                          {pendingSms && (
                            <ActionForm path="/settings/channels/verify.php" className="d-flex flex-wrap gap-2 align-items-center">
                              <span className="fs-13 w-100" id="my-channels-sms-sent">A code was texted to <strong>{pendingSms}</strong>. Enter it here:</span>
                              <input type="text" name="code" inputMode="numeric" pattern="\d{6}" className="form-control w-auto" placeholder="6-digit code"
                                     required id="my-channels-sms-code" aria-label="The code texted to you" />
                              <SubmitButton className="btn btn-light-brand" id="my-channels-sms-verify">Link the number</SubmitButton>
                            </ActionForm>
                          )}
                          <p className="fs-11 text-muted mt-2 mb-0">From {endpoint("sms")}. Texts you send it reach your assistant once the number is linked.</p>
                        </>
                      )}
                    </div>
                  </div>
                  <div className="card" id="my-channels-email">
                    <div className="card-header"><h5 className="card-title">Email</h5></div>
                    <div className="card-body">
                      {endpoint("email") === null ? <p className="text-muted mb-0">Your assistant has no mailbox yet.</p> : (
                        <>
                          <ActionForm path="/settings/channels/link.php" className="d-flex flex-wrap gap-2 align-items-center mb-3">
                            <input type="hidden" name="channel" value="email" />
                            <input type="email" name="address" className="form-control w-auto" placeholder="you@example.com" required
                                   key={pendingEmail ?? "none"} defaultValue={pendingEmail ?? ""}
                                   id="my-channels-email-address" aria-label="Your email address" />
                            <SubmitButton className="btn btn-primary" id="my-channels-email-send">{pendingEmail ? "Mail a new code" : "Mail me a code"}</SubmitButton>
                          </ActionForm>
                          {pendingEmail && (
                            <ActionForm path="/settings/channels/verify.php" className="d-flex flex-wrap gap-2 align-items-center">
                              <input type="hidden" name="channel" value="email" />
                              <span className="fs-13 w-100" id="my-channels-email-sent">
                                A code was mailed to <strong>{pendingEmail}</strong> from {endpoint("email")} — check Spam if it is not there. Enter it here:
                              </span>
                              <input type="text" name="code" inputMode="numeric" pattern="\d{6}" className="form-control w-auto" placeholder="6-digit code"
                                     required id="my-channels-email-code" aria-label="The code mailed to you" />
                              <SubmitButton className="btn btn-light-brand" id="my-channels-email-verify">Link the address</SubmitButton>
                            </ActionForm>
                          )}
                          <p className="fs-11 text-muted mt-2 mb-0">
                            Your assistant&apos;s mailbox is <code>{endpoint("email")}</code>. Mail you send it from a linked address reaches your
                            assistant, and replies thread in your mail client.
                          </p>
                        </>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </>
          )}
        </div>
      </>
    );
  });
}
