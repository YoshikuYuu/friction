// popup.js — runs in the extension popup window

document.addEventListener("DOMContentLoaded", () => {
  const actionBtn = document.getElementById("actionBtn");
  const closeBtn = document.getElementById("closeBtn");

  fetch("http://127.0.0.1:8000/home", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
  })

  // Main action button
  actionBtn.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });

  // Close button — closes the popup window
  closeBtn.addEventListener("click", () => {
    window.close();
  });
});
