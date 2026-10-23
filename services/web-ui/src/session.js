const TOKEN = "archive.token";
const NAME = "archive.name";
const NOTICE = "archive.notice";
const RETURN_TO = "archive.returnTo";

/** The staff token lives in sessionStorage: gone when the tab closes, never sent anywhere but the API. */
export const session = {
  token: () => sessionStorage.getItem(TOKEN),
  name: () => sessionStorage.getItem(NAME),
  signIn(token, name) {
    sessionStorage.setItem(TOKEN, token);
    sessionStorage.setItem(NAME, name);
  },
  rememberToken: (token) => sessionStorage.setItem(TOKEN, token),
  signOut() {
    sessionStorage.removeItem(TOKEN);
    sessionStorage.removeItem(NAME);
  },
  /** The token was refused mid-session: say so on the sign-in page, and remember where the person was. */
  expire(message, returnTo) {
    this.signOut();
    sessionStorage.setItem(NOTICE, message);
    sessionStorage.setItem(RETURN_TO, returnTo);
  },
  takeNotice() {
    const message = sessionStorage.getItem(NOTICE);
    sessionStorage.removeItem(NOTICE);
    return message;
  },
  takeReturnTo() {
    const path = sessionStorage.getItem(RETURN_TO);
    sessionStorage.removeItem(RETURN_TO);
    return path;
  },
};
