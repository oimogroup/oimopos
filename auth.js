const authSessionKey = "ashkana-auth-session-v1";
const loginForm = document.querySelector("#loginForm");
const loginInput = document.querySelector("#loginInput");
const passwordInput = document.querySelector("#passwordInput");
const loginError = document.querySelector("#loginError");
const loginNotice = document.querySelector("#loginNotice");
const submitButton = loginForm.querySelector("button[type='submit']");
const submitLabel = submitButton.querySelector("span");

const loginQuery = new URLSearchParams(location.search);
const terminalMode = loginQuery.get("mode") === "pos";
const requestedRegisterId = loginQuery.get("register");
window.AshkanaApi.setClientMode(terminalMode ? "pos" : "admin");
if (terminalMode) {
  document.title = "Oimo POS — активация кассы";
  document.body.classList.add("terminal-auth");
  document.querySelector("#authEyebrow").textContent = "Отдельное рабочее место";
  document.querySelector("#authHeroTitle").textContent = "Активируйте кассу на этом устройстве";
  document.querySelector("#authHeroDescription").textContent = "Сначала устройство входит в выбранную кассу. После этого каждый сотрудник работает под своим именем и личным PIN.";
  document.querySelector("#loginEyebrow").textContent = "Oimo POS";
  document.querySelector("#loginTitle").textContent = "Вход в кассу";
  document.querySelector("#loginDescription").textContent = "Логин и пароль кассы или учётная запись руководителя.";
  document.querySelector("#loginSecurityTitle").textContent = "Одна касса — одно устройство";
  document.querySelector("#loginSecurityText").textContent = "После активации сотрудник выбирает своё имя и вводит личный 4-значный PIN.";
  submitLabel.textContent = "Открыть кассу";
  loginInput.value = loginQuery.get("login") || "";
}
if (!terminalMode && loginQuery.has("login")) loginInput.value = loginQuery.get("login");
if (loginQuery.get("access") === "changed") loginNotice.classList.remove("hidden");
if (loginQuery.get("server") === "unavailable") showLoginError("Сервер Oimo недоступен. Запустите проект через Docker и обновите страницу.");

function showLoginError(message) {
  loginError.textContent = message;
  loginError.classList.remove("hidden");
}

async function restoreServerSession() {
  try {
    const response = await window.AshkanaApi.me();
    if (!response?.session) return;
    sessionStorage.setItem(authSessionKey, JSON.stringify(response.session));
    location.replace(response.session.route);
  } catch (error) {
    if (error.status && error.status !== 401) showLoginError(error.message);
  }
}

loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  loginError.classList.add("hidden");
  const login = loginInput.value.trim().toLowerCase();
  const password = passwordInput.value;
  submitButton.disabled = true;
  submitLabel.textContent = "Проверяем…";
  try {
    const response = await window.AshkanaApi.login(login, password, terminalMode ? requestedRegisterId : null);
    sessionStorage.setItem(authSessionKey, JSON.stringify(response.session));
    passwordInput.value = "";
    location.replace(response.session.route);
  } catch (error) {
    showLoginError(error.status === 401 ? "Неверный логин или пароль" : error.message);
    if (error.status === 401) passwordInput.select();
  } finally {
    submitButton.disabled = false;
    submitLabel.textContent = terminalMode ? "Открыть кассу" : "Войти";
  }
});

if (!loginQuery.has("login") && loginQuery.get("mode") !== "admin") restoreServerSession();
