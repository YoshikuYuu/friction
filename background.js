// background.js — Manifest V3 service worker

chrome.runtime.onInstalled.addListener(() => {
  console.log("Friction extension installed.");
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  // Handle messages from popup or content scripts here
  console.log("Background received message:", message, "from:", sender);
  sendResponse({ received: true });
  return true; // keep the message channel open for async responses
});
