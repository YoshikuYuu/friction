// popup.js — runs in the extension popup window

document.addEventListener("DOMContentLoaded", () => {
  const statusEl = document.getElementById("status");
  const actionBtn = document.getElementById("actionBtn");
  const pageInfoEl = document.getElementById("pageInfo");
  const closeBtn = document.getElementById("closeBtn");

  // Display the current tab's URL in the footer
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (tabs.length > 0) {
      const url = tabs[0].url || "";
      pageInfoEl.textContent = url;
      statusEl.textContent = "Ready";
    } else {
      statusEl.textContent = "No active tab";
    }
  });

  // Main action button
  actionBtn.addEventListener("click", () => {
    statusEl.textContent = "Running…";
    actionBtn.disabled = true;

    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs.length === 0) {
        statusEl.textContent = "No active tab found.";
        actionBtn.disabled = false;
        return;
      }

      // Example: send a message to the content script
      chrome.tabs.sendMessage(tabs[0].id, { action: "run" }, (response) => {
        if (chrome.runtime.lastError) {
          statusEl.textContent = "Error: " + chrome.runtime.lastError.message;
        } else {
          statusEl.textContent = response?.status ?? "Completed (no response)";
        }
        actionBtn.disabled = false;
      });
    });
  });

  // Close button — closes the popup window
  closeBtn.addEventListener("click", () => {
    window.close();
  });
});
