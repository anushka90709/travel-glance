(() => {
  const errorEl = document.getElementById("loginError");

  function showError(text) {
    errorEl.textContent = text;
    errorEl.hidden = false;
  }

  async function handleCredentialResponse(response) {
    errorEl.hidden = true;
    try {
      const res = await fetch("/auth/google", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: response.credential }),
      });
      const data = await res.json();
      if (!res.ok) {
        showError(data.error || "Sign-in failed. Please try again.");
        return;
      }
      window.location.href = "/";
    } catch (e) {
      showError("Couldn't reach the server. Please try again.");
    }
  }

  function initGoogleSignIn() {
    const clientId = document.body.dataset.googleClientId;
    if (!clientId) {
      showError("Google sign-in isn't configured yet.");
      return;
    }
    google.accounts.id.initialize({
      client_id: clientId,
      callback: handleCredentialResponse,
    });
    google.accounts.id.renderButton(document.getElementById("googleSignInBtn"), {
      type: "standard",
      theme: "filled_black",
      size: "large",
      shape: "pill",
      text: "continue_with",
      logo_alignment: "left",
      width: 320,
    });
  }

  window.onGoogleLibraryLoad = initGoogleSignIn;
})();
