document.addEventListener("DOMContentLoaded", () => {
  const toggle = document.querySelector("[data-nav-toggle]");
  const nav = document.getElementById("site-nav");

  if (toggle && nav) {
    toggle.addEventListener("click", () => {
      const open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  document.querySelectorAll("form[method='post']").forEach((form) => {
    form.addEventListener("submit", () => {
      form.querySelectorAll("button[type='submit']").forEach((button) => {
        button.setAttribute("aria-busy", "true");
      });
    });
  });
});

window.addEventListener("pageshow", () => {
  document.querySelectorAll("button[aria-busy]").forEach((button) => {
    button.removeAttribute("aria-busy");
  });
});
