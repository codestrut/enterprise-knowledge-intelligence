import { useState, type FormEvent } from "react";
import { ApiRequestError } from "./api/client";
import { Icon } from "./Icons";
import { useAuth } from "./AuthContext";

// Fixed, user-facing sign-in messages; raw server text is never rendered.
export function signInErrorMessage(cause: unknown): string {
  if (cause instanceof ApiRequestError) {
    if (cause.status === 401) return "Authentication failed. Check your credentials and account access.";
    if (cause.status === 429) return "Too many sign-in attempts. Wait a few minutes and try again.";
    if (cause.status === 422) return "Check the email and password and try again.";
    if (cause.status !== undefined && cause.status >= 500) return "Sign-in is temporarily unavailable. Try again shortly.";
  }
  if (cause instanceof TypeError) return "Cannot reach EKIP right now. Check your connection and try again.";
  return "Sign in could not be completed. Try again.";
}

export default function LoginPage() {
  const auth = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organisationId, setOrganisationId] = useState("");
  const [platformOperatorSignIn, setPlatformOperatorSignIn] = useState(false);
  const [error, setError] = useState("");
  const [prompt, setPrompt] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [visualAvailable, setVisualAvailable] = useState(true);
  const [usePosterFallback, setUsePosterFallback] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setPrompt("");
    auth.clearMessage();
    try {
      const result = await auth.signIn(
        email,
        password,
        platformOperatorSignIn ? undefined : organisationId || undefined,
        platformOperatorSignIn ? "platform" : "tenant",
      );
      // Keep the password until sign-in genuinely succeeds so an organisation choice needs no retyping.
      if (result === "signedIn") {
        setPassword("");
        if (platformOperatorSignIn) {
          window.history.replaceState({}, "", "/platform");
          window.dispatchEvent(new Event("ekip:navigate"));
        }
      } else if (result === "needsOrganisation") setPrompt("Choose an organisation to continue.");
      else setError("No active organisation is available for this account. Contact your administrator.");
    } catch (cause) {
      setError(signInErrorMessage(cause));
    }
  }

  function changeEmail(value: string) {
    setEmail(value);
    if (auth.organisationChoices.length > 0 || organisationId) {
      auth.clearChoices();
      setOrganisationId("");
      setPrompt("");
    }
  }

  return <main className={`login-page${visualAvailable ? " login-page--with-visual" : ""}`}>
    <section className="login-panel" aria-labelledby="login-title">
      <a className="login-brand" href="/" aria-label="EKIP home">
        <span className="brand-mark" aria-hidden="true"><span/><span/><span/><span/></span><span>EKIP</span>
      </a>
      <div className="login-copy">
        <p className="login-eyebrow">SECURE ORGANISATION WORKSPACE</p>
        <h1 id="login-title">Turn information into clarity.</h1>
        <p className="login-description">A secure, AI-powered knowledge platform for modern organisations.</p>
      </div>
      <form className="login-form" onSubmit={submit}>
        <label htmlFor="login-email">Work email</label>
        <input id="login-email" type="email" autoComplete="username" required value={email} onChange={(event) => changeEmail(event.target.value)} />
        <label htmlFor="login-password">Password</label>
        <div className="password-field">
          <input id="login-password" type={showPassword ? "text" : "password"} autoComplete="current-password" required value={password} onChange={(event) => setPassword(event.target.value)} />
          <button type="button" className="password-toggle" onClick={() => setShowPassword((visible) => !visible)} aria-label={showPassword ? "Hide password" : "Show password"}>{showPassword ? "Hide" : "Show"}</button>
        </div>
        <label className="login-scope-option"><input type="checkbox" checked={platformOperatorSignIn} onChange={(event) => { setPlatformOperatorSignIn(event.target.checked); setOrganisationId(""); auth.clearChoices(); setPrompt(""); setError(""); }} /> Sign in as a platform operator</label>
        {platformOperatorSignIn && <p className="login-scope-help">Use this option only for an account with an assigned platform role. Platform sessions do not receive tenant document access.</p>}
        {!platformOperatorSignIn && auth.organisationChoices.length > 0 && <><label htmlFor="login-organisation">Organisation</label><select id="login-organisation" required value={organisationId} onChange={(event) => setOrganisationId(event.target.value)}><option value="">Choose an organisation</option>{auth.organisationChoices.map((choice) => <option key={choice.id} value={choice.id}>{choice.name}</option>)}</select></>}
        {prompt && !error && <p role="status" className="login-prompt">{prompt}</p>}
        {(error || auth.message) && <p role="alert" className="login-error">{error || auth.message}</p>}
        <button className="login-submit" type="submit" disabled={auth.loading}>{auth.loading ? <><span className="login-spinner" aria-hidden="true"/>Signing in…</> : <>Sign in securely <Icon name="arrow"/></>}</button>
      </form>
      <p className="login-footnote">Access is managed by your organisation.</p>
    </section>
    {visualAvailable && <aside className="login-visual" aria-label="Research workspace">
      <div className="login-visual-card">
        <picture className="login-visual-picture">
          {!usePosterFallback && <source media="(prefers-reduced-motion: reduce)" srcSet="/images/ekip-login-research-rotation-poster.jpg" />}
          <img src={usePosterFallback ? "/images/ekip-login-research-rotation-poster.jpg" : "/images/ekip-login-research-rotation.gif"} alt="Researchers studying documents and digital information in a collaborative workspace" onError={() => usePosterFallback ? setVisualAvailable(false) : setUsePosterFallback(true)} />
        </picture>
        <div className="login-visual-caption"><span>KNOWLEDGE, CONNECTED</span><p>Make the insight in your organisation’s information easier to find and use.</p></div>
      </div>
    </aside>}
  </main>;
}
