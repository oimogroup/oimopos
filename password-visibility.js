(() => {
  const eye = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/></svg>';
  const eyeOff = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.2A11 11 0 0 1 12 5c6.4 0 10 7 10 7a15 15 0 0 1-3.1 3.8M6.2 6.2C3.5 8 2 12 2 12s3.6 7 10 7a10 10 0 0 0 3-.5"/></svg>';

  function addPasswordToggles() {
    document.querySelectorAll('input[type="password"]:not([data-password-visibility])').forEach((input) => {
      const wrapper = document.createElement('div');
      wrapper.className = 'password-visibility-field';
      input.parentNode.insertBefore(wrapper, input);
      wrapper.append(input);

      const button = document.createElement('button');
      button.className = 'password-visibility-toggle';
      button.type = 'button';
      button.setAttribute('aria-label', 'Показать пароль');
      button.setAttribute('aria-pressed', 'false');
      button.title = 'Показать пароль';
      button.innerHTML = eye;
      button.addEventListener('pointerdown', (event) => event.preventDefault());
      button.addEventListener('click', () => {
        const visible = input.type === 'password';
        input.type = visible ? 'text' : 'password';
        button.setAttribute('aria-label', visible ? 'Скрыть пароль' : 'Показать пароль');
        button.setAttribute('aria-pressed', String(visible));
        button.title = visible ? 'Скрыть пароль' : 'Показать пароль';
        button.innerHTML = visible ? eyeOff : eye;
      });
      wrapper.append(button);
      input.dataset.passwordVisibility = 'true';
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', addPasswordToggles, { once: true });
  } else {
    addPasswordToggles();
  }
})();
