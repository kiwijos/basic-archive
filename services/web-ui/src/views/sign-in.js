import { h } from "../dom.js";

/** Asks for the staff token and checks it with the API before letting anyone in. */
export function signInView({ api, session, onSignedIn }) {
  const problem = h("p", { class: "error", role: "alert" });
  const input = h("input", {
    id: "token",
    name: "token",
    type: "password",
    autocomplete: "off",
    spellcheck: "false",
    required: true,
  });
  const button = h("button", { type: "submit", class: "primary" }, "Sign in");

  const form = h(
    "form",
    {
      class: "stack",
      onsubmit: async (event) => {
        event.preventDefault();
        problem.textContent = "";
        const token = input.value.trim();
        if (!token) {
          problem.textContent = "Enter your staff token.";
          input.focus();
          return;
        }
        button.disabled = true;
        session.rememberToken(token);
        try {
          const who = await api.me();
          session.signIn(token, who.name);
          onSignedIn();
        } catch (error) {
          session.signOut();
          problem.textContent = error.message;
          input.focus();
        } finally {
          button.disabled = false;
        }
      },
    },
    h("label", { for: "token" }, "Staff token"),
    input,
    button,
    problem,
  );

  return {
    title: "Sign in",
    element: h(
      "section",
      { class: "narrow" },
      h("h1", {}, "Sign in"),
      h("p", {}, "Enter the staff token you were given. It is kept only for this browser tab."),
      form,
    ),
    focus: input,
  };
}
