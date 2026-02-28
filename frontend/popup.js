// popup.js — runs in the extension popup window

document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("status");
  const actionBtn = document.getElementById("actionBtn");
  const pageInfoEl = document.getElementById("pageInfo");
  const closeBtn = document.getElementById("closeBtn");

  // Main action button
  actionBtn.addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
  });

  // Close button — closes the popup window
  closeBtn.addEventListener("click", () => {
    window.close();
  });
});
