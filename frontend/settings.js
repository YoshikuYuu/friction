const inputDesc = document.getElementById("blockedInputDesc");
const inputTitle = document.getElementById("blockedInputTitle");
const addBtn = document.getElementById("addBtn");
const doneBtn = document.getElementById("doneBtn")
const blockedList = document.getElementById("blockedList");
const container = document.getElementById("tagContainer");

let positiveTags = new Set();
let negativeTags = new Set();
let title = "";
let desc = "";
let blockType = "";

let blockedItems = JSON.parse(localStorage.getItem("blockedItems")) || {};

const titleCount = document.getElementById("charCountTitle");
const descCount = document.getElementById("charCountDesc");

inputTitle.addEventListener("input", () => {
    titleCount.textContent = inputTitle.value.length;
});

inputDesc.addEventListener("input", () => {
    descCount.textContent = inputDesc.value.length;
});

function renderList() {
    blockedList.innerHTML = "";

    // Loop through dictionary entries: [key, value]
    Object.entries(blockedItems).forEach(([key, item]) => {
        console.log("key: " + key + ", item: " + item)
        const li = document.createElement("li");

        li.innerHTML = `
            <strong>${key}</strong><br>
            <small>${item.desc}</small>
        `;

        const removeBtn = document.createElement("button");
        removeBtn.textContent = "Remove";
        removeBtn.classList.add("remove-btn");
        removeBtn.onclick = () => removeItem(key); // Use key instead of index

        li.appendChild(removeBtn);
        blockedList.appendChild(li);
    });

    localStorage.setItem("blockedItems", JSON.stringify(blockedItems));
}

// Updated remove function for dictionary
function removeItem(key) {
    delete blockedItems[key];  // remove by key
    renderList();               // re-render the list
}

function addItem() {
    title = inputTitle.value.trim();
    desc = inputDesc.value.trim();
    blockType = document.getElementById("choices").value;

    const descPackage = { name: title, desc: desc, blockType: blockType }


    if (title === "" || desc === "") return;

    fetch("http://127.0.0.1:8000/description", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(descPackage)
    }) 
    .then(res => res.json())
    .then(data => {
        const success = data.status === "success";
        console[success ? "log" : "error"](data.msg || data);
        chrome.runtime.sendMessage({
            action: "updateUI",
            status: success ? "success" : "error",
            message: data.tags
        });
        if (success) {
            data.tags.forEach(str => {
                const span = document.createElement("span");
                container.appendChild(span);
                span.classList.add("tag");

                const spanText = document.createElement("span")
                spanText.textContent = str;
                span.appendChild(spanText)
                spanText.classList.add("spantext");

                const yesButton = document.createElement("button");
                yesButton.classList.add("pnButton")
                yesButton.textContent = "✓";

                // Create "No" button
                const noButton = document.createElement("button");
                noButton.classList.add("pnButton")
                noButton.textContent = "⨉";

                yesButton.addEventListener("click", () => {
                    yesButton.style.borderColor = "#f4bd5d"
                    yesButton.style.color = "#f4bd5d"
                    noButton.style.borderColor = "#807a70"
                    noButton.style.color = "#807a70"
                    if (!(positiveTags.has(str))) {
                        positiveTags.add(str)
                    }
                    if (negativeTags.has(str)) {
                        negativeTags.remove(str)
                    }
                });
                noButton.addEventListener("click", () => {
                    yesButton.style.borderColor = "#807a70"
                    yesButton.style.color = "#807a70"
                    noButton.style.borderColor = "#f4bd5d"
                    noButton.style.color = "#f4bd5d"
                    if (!(negativeTags.has(str))) {
                        negativeTags.add(str)
                    }
                    if (positiveTags.has(str)) {
                        positiveTags.remove(str)
                    }
                });

                // Append buttons to the span
                span.appendChild(yesButton);
                span.appendChild(noButton);

                // Optional: add a space between spans
                container.appendChild(document.createTextNode(" "));
            });
        }
    })
    .catch(err => {
        console.error("Error:", err);
        //
    });
}

function doneItem() {
    blockedItems[title] = {
        desc: desc,
        positiveTags: Array.from(positiveTags),
        negativeTags: Array.from(negativeTags),
        blockType: blockType
    };

    const tabPackage = { name: title, desc: desc, positiveTags: Array.from(positiveTags), negativeTags: Array.from(negativeTags), blockType: blockType }

    fetch("http://127.0.0.1:8000/tags", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(tabPackage)
    }) 
    .then(res => res.json())
    .then(data => {
        const success = data.status === "success";
        console[success ? "log" : "error"](data.msg || data);
        chrome.runtime.sendMessage({
            action: "updateUI",
            status: success ? "success" : "error",
            message: data.tags
        });
    });

    inputTitle.value = "";
    inputDesc.value = "";
    container.innerHTML = "";

    titleCount.textContent = "0";
    descCount.textContent = "0";
    document.getElementById("choices").selectedIndex = 0;

    renderList();
}

doneBtn.addEventListener("click", doneItem);
addBtn.addEventListener("click", addItem);
const div1 = document.getElementById("div1");
const div2 = document.getElementById("div2");

let fadeDiv2 = true;
function fadeOut(element) {
    element.classList.remove("show");

    element.addEventListener("transitionend", function handler() {
        element.style.display = "none";
        element.removeEventListener("transitionend", handler);
    });

    setTimeout(() => {
        console.log("This runs after 1 second");
        if (fadeDiv2) {
            fadeIn(div2);
        } else {
            fadeIn(div1);
        }
    }, 600);
}

function fadeIn(element) {
  element.style.display = "block";

  // allow display change to apply before adding class
  requestAnimationFrame(() => {
    element.classList.add("show");
  });
}

addBtn.addEventListener("click", () => {
    fadeDiv2 = true;
    fadeOut(div1);
});

doneBtn.addEventListener("click", () => {
    fadeDiv2 = false;
    fadeOut(div2);
});

renderList();
