let lastPromise = Promise.resolve();
uuid = "";

function toBase64(file) {
    return new Promise((resolve, reject) => {
        const r = new FileReader();
        r.readAsDataURL(file);
        r.onload = () => resolve(r.result);
        r.onerror = (error) => reject(error);
    });
}

function appendOutput(src, seed, config) {
    let outputNode = document.createElement("figure");
    
    let variations = config.with_variations;
    if (config.variation_amount > 0) {
        variations = (variations ? variations + ',' : '') + seed + ':' + config.variation_amount;
    }
    let baseseed = (config.with_variations || config.variation_amount > 0) ? config.seed : seed;
    let altText = baseseed + ' | ' + (variations ? variations + ' | ' : '') + config.prompt;

    // img needs width and height for lazy loading to work
    const figureContents = `
        <a href="${src}" target="_blank">
            <img src="${src}"
                 alt="${altText}"
                 title="${altText}"
                 loading="lazy"
                 width="256"
                 height="256">
        </a>
        <figcaption>${seed}</figcaption>
    `;

    outputNode.innerHTML = figureContents;
    let figcaption = outputNode.querySelector('figcaption');

    // Reload image config
    figcaption.addEventListener('click', () => {
        let form = document.querySelector("#generate-form");
        for (const [k, v] of new FormData(form)) {
            if (k == 'initimg') { continue; }
            form.querySelector(`*[name=${k}]`).value = config[k];
        }

        document.querySelector("#seed").value = baseseed;
        document.querySelector("#with_variations").value = variations || '';
        if (document.querySelector("#variation_amount").value <= 0) {
            document.querySelector("#variation_amount").value = 0.2;
        }

        saveFields(document.querySelector("#generate-form"));
    });

    document.querySelector("#results").prepend(outputNode);
}

function saveFields(form) {
    for (const [k, v] of new FormData(form)) {
        if (typeof v !== 'object') { // Don't save 'file' type
            localStorage.setItem(k, v);
        }
    }
}

function loadFields(form) {
    for (const [k, v] of new FormData(form)) {
        const item = localStorage.getItem(k);
        if (item != null) {
            form.querySelector(`*[name=${k}]`).value = item;
        }
    }
}

function clearFields(form) {
    localStorage.clear();
    let prompt = form.prompt.value;
    form.reset();
    form.prompt.value = prompt;
}

const BLANK_IMAGE_URL = 'data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg"/>';
async function generateSubmit(form) {
    const prompt = document.querySelector("#prompt").value;

    // Convert file data to base64
    let formData = Object.fromEntries(new FormData(form));
    formData.initimg_name = formData.initimg.name
    formData.initimg = formData.initimg.name !== '' ? await toBase64(formData.initimg) : null;

    let strength = formData.strength;
    let totalSteps = formData.initimg ? Math.floor(strength * formData.steps) : formData.steps;

    let progressSectionEle = document.querySelector('#progress-section');
    progressSectionEle.style.display = 'initial';
    let progressEle = document.querySelector('#progress-bar');
    let progressTextEle = document.querySelector('#progress-bar-text');
    progressEle.setAttribute('max', totalSteps);
    let progressImageEle = document.querySelector('#progress-image');
    progressImageEle.src = BLANK_IMAGE_URL;

    progressImageEle.style.display = {}.hasOwnProperty.call(formData, 'progress_images') ? 'initial': 'none';

    // Post as JSON, using Fetch streaming to get results
    fetch(form.action, {
        method: form.method,
        body: JSON.stringify(formData),
    }).then(async (response) => {
        const reader = response.body.getReader();

        let noOutputs = true;
        while (true) {
            let {value, done} = await reader.read();
            value = new TextDecoder().decode(value);
            if (done) {
                uuid = "";
                progressSectionEle.style.display = 'none';
                break;
            }

            for (let event of value.split('\n').filter(e => e !== '')) {
                const data = JSON.parse(event);
                uuid = data.uuid
                
                if (data.event === 'result') {
                    noOutputs = false;
                    appendOutput("job/image?uuid=" + data.uuid, data.seed, data.config);
                    progressTextEle.innerHTML = totalSteps + "/" + totalSteps
                    progressEle.setAttribute('value', 0);
                    progressEle.setAttribute('max', totalSteps);
                
                } else if (data.event === 'upscaling-started') {
                    document.getElementById("processing_cnt").textContent=data.processed_file_cnt;
                    document.getElementById("scaling-inprocess-message").style.display = "block";
                
                } else if (data.event === 'upscaling-done') {
                    document.getElementById("scaling-inprocess-message").style.display = "none";
                
                } else if (data.event === 'step') {
                    document.getElementById("queued-message").style.display = "none";
                    progressEle.setAttribute('value', data.step);
                    progressTextEle.innerHTML = data.step +  "/" + totalSteps
                    if (data.url) {
                        progressImageEle.src = "job/image/intermediates?image=" + data.url;
                    }
                } else if (data.event === 'canceled') {
                    // avoid alerting as if this were an error case
                    noOutputs = false;
                } else if (data.event === "queued") {
                    progressImageEle.src = BLANK_IMAGE_URL;
                    document.getElementById("queued-message").style.display = "block";
                    document.getElementById("queued-message").innerHTML = "<b>Your prompt is queued, position: " + data.jobpos.pos + "</b>";
                }
            }
        }

        // Re-enable form, remove no-results-message
        form.querySelector('fieldset').removeAttribute('disabled');
        document.querySelector("#prompt").value = prompt;
        document.querySelector('progress').setAttribute('value', '0');

        if (noOutputs) {
            alert("Error occurred while generating.");
        }
    });

    // Disable form while generating
    form.querySelector('fieldset').setAttribute('disabled','');
    document.querySelector("#prompt").value = `Generating: "${prompt}"`;
}

async function processStatus() {
    const response = await fetch('/status');
    const status = await response.json();
    const gpu = status.nvidia.nvidia_smi_log.gpu
    console.log(status);
    let statusSection = document.querySelector('#status-section');
    
    updateString = "<span><i><b>GPU</b>: " + gpu.utilization.gpu_util + " ( " + gpu.temperature.gpu_temp + " / " + gpu.power_readings.power_draw + " )" 
    updateString += "<br><b>Queue size</b>: " + status.queuesize 
    statusSection.innerHTML = updateString + "</span>"
}   

function update() {
  lastPromise = lastPromise.then(processStatus, processStatus);
}

window.onload = async () => {
    setInterval(update, 1000);
    document.querySelector("#prompt").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        const form = e.target.form;
        generateSubmit(form);
      }
    });
    document.querySelector("#generate-form").addEventListener('submit', (e) => {
        e.preventDefault();
        const form = e.target;

        generateSubmit(form);
    });
    document.querySelector("#generate-form").addEventListener('change', (e) => {
        saveFields(e.target.form);
    });
    document.querySelector("#reset-seed").addEventListener('click', (e) => {
        document.querySelector("#seed").value = -1;
        saveFields(e.target.form);
    });
    document.querySelector("#reset-all").addEventListener('click', (e) => {
        clearFields(e.target.form);
    });
    document.querySelector("#remove-image").addEventListener('click', (e) => {
        initimg.value=null;
    });
    loadFields(document.querySelector("#generate-form"));

    document.querySelector('#cancel-button').addEventListener('click', () => {
        fetch('/job/cancel?uuid=' + uuid).catch(e => {
            console.error(e);
        });
    });
    document.documentElement.addEventListener('keydown', (e) => {
      if (e.key === "Escape")
        fetch('/job/cancel?uuid=' + uuid).catch(err => {
          console.error(err);
        });
    });
};
