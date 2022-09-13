function toBase64(file) {
    return new Promise((resolve, reject) => {
        const r = new FileReader();
        r.readAsDataURL(file);  
        r.onload = () => resolve(r.result);
        r.onerror = (error) => reject(error);
    });
}

function appendOutput(src, seed, config) {
    let outputNode = document.createElement("img");
    outputNode.src = src;

    let altText = seed.toString() + " | " + config.prompt;
    outputNode.alt = altText;
    outputNode.title = altText;

    // Reload image config
    outputNode.addEventListener('click', () => {
        let form = document.querySelector("#generate-form");
        for (const [k, v] of new FormData(form)) {
            form.querySelector(`*[name=${k}]`).value = config[k];
        }
        document.querySelector("#seed").value = seed;

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
    
    formData.initimg = formData.initimg.name !== '' ? await toBase64(formData.initimg) : null;

    let strength = formData.strength;
    let totalSteps = formData.initimg ? Math.floor(strength * formData.steps) : formData.steps;

    let progressSectionEle = document.querySelector('#progress-section');
    progressSectionEle.style.display = 'initial';
    let progressEle = document.querySelector('#progress-bar');
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
                progressSectionEle.style.display = 'none';
                break;
            }

            for (let event of value.split('\n').filter(e => e !== '')) {
                console.log(event);
                const data = JSON.parse(event);
                
                document.getElementById("info").innerHTML = `\n<h5><i>GPU: ${data.gpu.util} (${data.gpu.temp} / ${data.gpu.power})</h5></i>`

                if (data.event === 'result') {
                    document.getElementById("scaling-inprocess-message").style.display = "none";
                    noOutputs = false;
                    document.querySelector("#no-results-message")?.remove();
                    appendOutput("job/image?uuid=" + data.uuid, data.seed, data.config);
                    progressEle.setAttribute('value', 0);
                    progressEle.setAttribute('max', totalSteps);
               
                } else if (data.event === 'upscaling-started') {
                    document.getElementById("processing_cnt").textContent=data.processed_file_cnt;
                    document.getElementById("scaling-inprocess-message").style.display = "block";
                
                } else if (data.event === 'upscaling-done') {
                    document.getElementById("scaling-inprocess-message").style.display = "none";
               
                } else if (data.event === 'step') {
                    progressEle.setAttribute('value', data.step);
                    document.getElementById("queued-message").style.display = "none";
                    if (data.url) {
                        //progressImageEle.src = data.url;
                        progressImageEle.src = "job/image?uuid=" + data.uuid;
                    }
                
                } else if (data.event === 'canceled') {
                    // avoid alerting as if this were an error case
                    noOutputs = false;
                
                } else if (data.event === "queued") {
                    document.getElementById("queued-message").style.display = "block";
                    document.getElementById("queued-message").innerHTML = "<b>Your prompt is queued, position: " + data.jobpos.pos + "</b>";
                }
            }
        }

        // Re-enable form, remove no-results-message
        form.querySelector('fieldset').removeAttribute('disabled');
        document.querySelector("#prompt").value = prompt;
        document.querySelector('progress').setAttribute('value', '0');
        document.getElementById("info").innerHTML = ""; 
        if (noOutputs) {
            alert("Error occurred while generating.");
        }
    });

    // Disable form while generating
    form.querySelector('fieldset').setAttribute('disabled','');
    document.querySelector("#prompt").value = `Generating: "${prompt}"`;
}

window.onload = () => {
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

    loadFields(document.querySelector("#generate-form"));

    document.querySelector('#cancel-button').addEventListener('click', () => {
        fetch('/cancel').catch(e => {
            console.error(e);
        });
    });

};
