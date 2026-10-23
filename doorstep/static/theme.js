// Light unless this browser chose dark. Loaded in <head>, so a dark page never
// flashes white first; any button with id="theme" switches it.
(() => {
  const root = document.documentElement;
  const KEY = "doorstep-theme";
  try { if (localStorage.getItem(KEY) === "dark") root.dataset.theme = "dark"; } catch (e) {}
  window.addEventListener("DOMContentLoaded", () => {
    const button = document.getElementById("theme");
    if (!button) return;
    const label = () => { button.textContent = root.dataset.theme === "dark" ? "Light mode" : "Dark mode"; };
    label();
    button.addEventListener("click", () => {
      if (root.dataset.theme === "dark") delete root.dataset.theme;
      else root.dataset.theme = "dark";
      try { localStorage.setItem(KEY, root.dataset.theme || "light"); } catch (e) {}
      label();
    });
  });
})();
