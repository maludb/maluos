/* eslint-disable @next/next/no-img-element */
// The design system's auth skeleton (login, 2FA, register, reset) — markup copied from
// app/views/auth-layout.php, not composed. Always in the theme's dark skin (components/shell/DarkSkin).
import DarkSkin from "@/components/shell/DarkSkin";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="auth-minimal-wrapper">
      <DarkSkin />
      <div className="auth-minimal-inner">
        <div className="minimal-card-wrapper">
          <div className="card mb-4 mt-5 mx-4 mx-sm-0 position-relative">
            <div className="wd-50 bg-white p-2 rounded-circle shadow-lg position-absolute translate-middle top-0 start-50">
              <img src="/assets/images/logo-abbr.png" alt="" className="img-fluid" />
            </div>
            <div className="card-body p-sm-5">{children}</div>
          </div>
        </div>
      </div>
    </main>
  );
}
