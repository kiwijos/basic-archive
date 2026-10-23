const TOKEN = "archive.token";
const NAME = "archive.name";

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
};
