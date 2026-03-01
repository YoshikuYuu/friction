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
            if (data.blockMode === "strict") {
              console.log("Here REACHEHHEDHEDH")
              chrome.tabs.update(tabId, { url: chrome.runtime.getURL("blocked.html") });
            } else if (data.blockMode === "warn") {
              console.log("Warn REACHED in background.js :3")
              chrome.scripting.executeScript({
                target: { tabId: tabId },
                func: function() {
                  // Check if the iframe already exists
                  const popup = document.createElement("div");
                  popup.textContent = "Hey! Are you supposed to be on this page?";
                  
                  const popContainer = document.createElement("div");
                  Object.assign(popContainer.style, {
                    display: "flex",
                    flexDirection: "row"
                  })

                  const blingirl = document.createElement("img");
                  blingirl.src = chrome.runtime.getURL("assets/blingirl2.webp");
                  Object.assign(blingirl.style, {
                    height: "150px",
                    width: "250px"
                  })

                  // Create Continue button
                  const continueBtn = document.createElement("button");
                  continueBtn.textContent = "Yes, continue ⟶";

                  // Style button
                  Object.assign(continueBtn.style, {
                    height: "40px",
                    marginTop: "15px",
                    padding: "8px 14px",
                    backgroundColor: "#eeede9",
                    color: "#1b1b1b",
                    border: "none",
                    borderRadius: "4px",
                    cursor: "pointer",
                    fontSize: "16px"
                  });

                  // Close popup on click
                  continueBtn.addEventListener("click", () => {
                    popup.remove(); // removes it from the DOM
                  });

                  popContainer.appendChild(continueBtn);
                  popContainer.appendChild(blingirl);
                  popup.appendChild(popContainer)

                  // Style it like a popup
                  Object.assign(popup.style, {
                    display: "flex",
                    flexDirection: "column",
                    position: "fixed",
                    top: "20px",
                    right: "20px",
                    height: "150px",
                    backgroundColor: "#1b1b1b",
                    color: "#eeede9",
                    padding: "20px",
                    fontSize: "20px",
                    fontFamily: "sans-serif",
                    borderRadius: "8px",
                    boxShadow: "0 4px 12px rgba(0,0,0,0.3)",
                    zIndex: 999999
                  });

                  document.body.appendChild(popup);
                }
              });
            } else {
              console.log("Not reached")
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
