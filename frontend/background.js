// chrome.runtime.onInstalled.addListener(() => {
//   console.log("Friction extension installed.");
// });

/**
 * Retrieves the URL and title of a Chrome tab by its ID.
 *
 * @param {number} tabId - The ID of the tab whose info should be retrieved.
 * @param {(info: {url: string|null, title: string|null}) => void} callback - Function invoked with
 *        the tab's URL and title on success, or nulls if an error occurs.
 */
function getTabInfo(tabId, callback) {
    chrome.tabs.get(tabId, (tab) => {
        if (chrome.runtime.lastError) {
            console.error("Error getting tab:", chrome.runtime.lastError);
            callback({ url: null, title: null }); // Return nulls on error
        } else {
            callback({ url: tab.url, title: tab.title }); // Return URL and title
        }
    });
}

chrome.tabs.onUpdated.addListener((tabId, changeInfo, tab) => {
  if (changeInfo.status !== "complete") return;
  console.log("tab updated: " + tabId);

  getTabInfo(tabId, ({ url, title }) => {
    console.log("tab updated url:", url);
    console.log("tab updated title:", title);

    if (url) {
      const tabInfo = {url: url, title: title};
      fetch("http://127.0.0.1:8000/checktab", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(tabInfo) // send both url and title
      })
      .then(res => res.json())
      .then(data => {
        const success = data.status === "success";
        console[success ? "log" : "error"](data.msg || data);
        if (success) {
            if (data.msg === "block") {
              chrome.tabs.update(tabId, { url: chrome.runtime.getURL("blocked.html") });
            }
        }
      })
      .catch(err => {
          console.error("Error:", err);
          // Optional: handle fetch error
      });
    }
  });
});