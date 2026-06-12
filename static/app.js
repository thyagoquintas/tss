const form = document.querySelector("#ttsForm");
const textInput = document.querySelector("#textInput");
const voiceInput = document.querySelector("#voiceInput");
const speedInput = document.querySelector("#speedInput");
const speedValue = document.querySelector("#speedValue");
const imageInput = document.querySelector("#imageInput");
const addImagesButton = document.querySelector("#addImagesButton");
const imagePanel = document.querySelector("#imagePanel");
const imageQueue = document.querySelector("#imageQueue");
const emptyQueue = document.querySelector("#emptyQueue");
const imageName = document.querySelector("#imageName");
const ocrMeta = document.querySelector("#ocrMeta");
const ocrButton = document.querySelector("#ocrButton");
const clearButton = document.querySelector("#clearButton");
const submitButton = document.querySelector("#submitButton");
const statusLine = document.querySelector("#statusLine");
const outputPanel = document.querySelector("#outputPanel");
const audioPlayer = document.querySelector("#audioPlayer");
const audioMeta = document.querySelector("#audioMeta");
const downloadLink = document.querySelector("#downloadLink");
const deviceStatus = document.querySelector("#deviceStatus");

const MAX_TEXT_LENGTH = 10000;
const APP_BASE_URL = new URL("./", window.location.href);
let imageItems = [];
let nextImageId = 1;

function appUrl(path) {
  return new URL(path.replace(/^\/+/, ""), APP_BASE_URL).toString();
}

function setStatus(message, isError = false) {
  statusLine.textContent = message;
  statusLine.classList.toggle("error", isError);
}

function setBusy(isBusy, label = "Gerando...") {
  submitButton.disabled = isBusy;
  clearButton.disabled = isBusy;
  ocrButton.disabled = isBusy;
  addImagesButton.disabled = isBusy;
  submitButton.textContent = isBusy ? label : "Gerar MP3";
}

function setOcrBusy(isBusy) {
  submitButton.disabled = isBusy;
  clearButton.disabled = isBusy;
  ocrButton.disabled = isBusy;
  addImagesButton.disabled = isBusy;
  ocrButton.textContent = isBusy ? "Extraindo..." : "Extrair texto";
}

function updateSpeedLabel() {
  speedValue.textContent = `${Number(speedInput.value).toFixed(2)}x`;
}

function updateImageSummary() {
  if (imageItems.length === 0) {
    imageName.textContent = "Cole imagens, adicione arquivos ou digite o texto no proximo passo.";
  } else if (imageItems.length === 1) {
    imageName.textContent = `1 imagem: ${imageItems[0].file.name}`;
  } else {
    imageName.textContent = `${imageItems.length} imagens na fila`;
  }
}

function formatBytes(bytes) {
  if (bytes < 1024 * 1024) {
    return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function renderImageQueue() {
  imageQueue.innerHTML = "";
  emptyQueue.hidden = imageItems.length > 0;

  imageItems.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "image-card";

    const thumb = document.createElement("img");
    thumb.className = "image-thumb";
    thumb.src = item.url;
    thumb.alt = "";

    const info = document.createElement("div");
    info.className = "image-info";

    const title = document.createElement("strong");
    title.textContent = `${index + 1}. ${item.file.name}`;

    const meta = document.createElement("span");
    meta.textContent = formatBytes(item.file.size);

    const tools = document.createElement("div");
    tools.className = "image-tools";

    const up = document.createElement("button");
    up.className = "mini-button";
    up.type = "button";
    up.textContent = "^";
    up.title = "Subir";
    up.disabled = index === 0;
    up.addEventListener("click", () => moveImage(index, -1));

    const down = document.createElement("button");
    down.className = "mini-button";
    down.type = "button";
    down.textContent = "v";
    down.title = "Descer";
    down.disabled = index === imageItems.length - 1;
    down.addEventListener("click", () => moveImage(index, 1));

    const remove = document.createElement("button");
    remove.className = "mini-button";
    remove.type = "button";
    remove.textContent = "x";
    remove.title = "Remover";
    remove.addEventListener("click", () => removeImage(item.id));

    info.append(title, meta);
    tools.append(up, down, remove);
    card.append(thumb, info, tools);
    imageQueue.appendChild(card);
  });

  updateImageSummary();
}

function addImageFiles(files) {
  const images = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (images.length === 0) {
    setStatus("Nenhuma imagem encontrada.", true);
    return;
  }

  images.forEach((file) => {
    imageItems.push({
      id: nextImageId,
      file,
      url: URL.createObjectURL(file),
    });
    nextImageId += 1;
  });

  outputPanel.hidden = true;
  ocrMeta.textContent = "O texto final para narracao fica aqui.";
  setStatus(`${images.length} imagem(ns) adicionada(s).`);
  renderImageQueue();
}

function removeImage(id) {
  const item = imageItems.find((image) => image.id === id);
  if (item) {
    URL.revokeObjectURL(item.url);
  }
  imageItems = imageItems.filter((image) => image.id !== id);
  renderImageQueue();
}

function moveImage(index, direction) {
  const target = index + direction;
  if (target < 0 || target >= imageItems.length) {
    return;
  }
  [imageItems[index], imageItems[target]] = [imageItems[target], imageItems[index]];
  renderImageQueue();
}

async function loadStatus() {
  try {
    const response = await fetch(appUrl("api/status"));
    const data = await response.json();
    deviceStatus.textContent = data.cuda ? `CUDA: ${data.label}` : "CPU";
  } catch {
    deviceStatus.textContent = "Dispositivo indisponivel";
  }
}

async function loadVoices() {
  try {
    const response = await fetch(appUrl("api/voices"));
    const data = await response.json();
    voiceInput.innerHTML = "";

    data.voices.forEach((voice) => {
      const option = document.createElement("option");
      option.value = voice.id;
      option.textContent = voice.label;
      option.title = voice.description;
      voiceInput.appendChild(option);
    });

    voiceInput.value = data.default_voice;
  } catch {
    setStatus("Nao foi possivel carregar as vozes.", true);
  }
}

async function requestOcr() {
  if (imageItems.length === 0) {
    throw new Error("Adicione pelo menos uma imagem.");
  }

  const formData = new FormData();
  imageItems.forEach((item) => {
    formData.append("images", item.file, item.file.name);
  });

  const response = await fetch(appUrl("api/ocr"), {
    method: "POST",
    body: formData,
  });
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "Falha ao extrair texto.");
  }

  if (!data.text || !data.text.trim()) {
    throw new Error("Nenhum texto foi encontrado nas imagens.");
  }

  return data;
}

function setTextFromOcr(data) {
  const text = data.text.trim().slice(0, MAX_TEXT_LENGTH);
  textInput.value = text;
  ocrMeta.textContent = `${data.pages?.length || imageItems.length} pagina(s) extraida(s).`;
}

async function extractTextFromImages() {
  setOcrBusy(true);
  setStatus("Extraindo texto...");

  try {
    const data = await requestOcr();
    setTextFromOcr(data);
    outputPanel.hidden = true;
    setStatus(`Texto extraido por ${data.engine || "OCR"}.`);
    textInput.focus();
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setOcrBusy(false);
  }
}

async function generateAudio(event) {
  event.preventDefault();
  let text = textInput.value.trim();

  if (!text && imageItems.length === 0) {
    setStatus("Informe um texto ou adicione imagens.", true);
    textInput.focus();
    return;
  }

  setBusy(true);

  try {
    if (!text && imageItems.length > 0) {
      setStatus("Extraindo texto...");
      setBusy(true, "Extraindo...");
      const ocrData = await requestOcr();
      setTextFromOcr(ocrData);
      text = textInput.value.trim();
    }

    setStatus("Gerando MP3...");
    setBusy(true, "Gerando...");
    const response = await fetch(appUrl("api/generate"), {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        text,
        voice: voiceInput.value || "pf_dora",
        speed: Number(speedInput.value),
      }),
    });

    const data = await response.json();
    if (!response.ok) {
      throw new Error(data.detail || "Falha ao gerar MP3.");
    }

    const audioUrl = `${appUrl(data.audio_url)}?t=${Date.now()}`;
    audioPlayer.src = audioUrl;
    downloadLink.href = audioUrl;
    downloadLink.download = data.filename;
    audioMeta.textContent = data.filename;
    outputPanel.hidden = false;
    setStatus("Pronto.");
    audioPlayer.play().catch(() => {});
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setBusy(false);
  }
}

function clearAll() {
  imageItems.forEach((item) => URL.revokeObjectURL(item.url));
  imageItems = [];
  textInput.value = "";
  imageInput.value = "";
  ocrMeta.textContent = "O texto final para narracao fica aqui.";
  outputPanel.hidden = true;
  audioPlayer.removeAttribute("src");
  audioPlayer.load();
  setStatus("");
  renderImageQueue();
  textInput.focus();
}

addImagesButton.addEventListener("click", () => imageInput.click());

imageInput.addEventListener("change", () => {
  addImageFiles(imageInput.files);
  imageInput.value = "";
});

document.addEventListener("paste", (event) => {
  const files = Array.from(event.clipboardData?.files || []);
  const images = files.filter((file) => file.type.startsWith("image/"));
  if (images.length === 0) {
    return;
  }

  event.preventDefault();
  addImageFiles(images);
  imagePanel.focus();
});

ocrButton.addEventListener("click", extractTextFromImages);
clearButton.addEventListener("click", clearAll);
speedInput.addEventListener("input", updateSpeedLabel);
form.addEventListener("submit", generateAudio);

updateSpeedLabel();
renderImageQueue();
loadStatus();
loadVoices();
