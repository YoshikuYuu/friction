// content.js — injected into every page

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.action === "run") {
    // Add page-level logic here
    console.log("Friction content script: run action received.");
    sendResponse({ status: "Done" });
  }
  return true; // keep the message channel open for async responses
});
