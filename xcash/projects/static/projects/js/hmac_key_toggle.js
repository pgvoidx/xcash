(function () {
  const DATA_TOGGLE = "data-password-toggle";
  const BUTTON_SELECTOR = "[data-password-toggle-button]";
  const ICON_SELECTOR = "[data-password-toggle-icon]";

  function updateIcon(icon, visible) {
    if (!icon) {
      return;
    }

    const visibleLabel = icon.dataset.visibleLabel || "visibility";
    const hiddenLabel = icon.dataset.hiddenLabel || "visibility_off";

    icon.textContent = visible ? visibleLabel : hiddenLabel;
  }

  document.addEventListener("click", function (event) {
    const button = event.target.closest(BUTTON_SELECTOR);
    if (!button) {
      return;
    }

    const container = button.closest(`[${DATA_TOGGLE}]`);
    if (!container) {
      return;
    }

    const input = container.querySelector("[data-password-toggle-input]");
    if (!input) {
      return;
    }

    if (input.type === "password") {
      input.type = "text";
      updateIcon(container.querySelector(ICON_SELECTOR), true);
      button.setAttribute("aria-pressed", "true");
    } else {
      input.type = "password";
      updateIcon(container.querySelector(ICON_SELECTOR), false);
      button.setAttribute("aria-pressed", "false");
    }
  });
})();
