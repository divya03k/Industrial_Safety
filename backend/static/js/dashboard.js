function showPage(page){

let pages=document.querySelectorAll(".page")

pages.forEach(p=>p.style.display="none")

document.getElementById(page).style.display="block"

document.getElementById("pageTitle").innerText=page

// ✅ ADD THIS
if(page === "alerts"){
    loadAlerts()
}
if(page === "analytics"){
    loadAnalytics()
}
}
let analyticsChart;
let analyticsData = null;
showPage("dashboard")
let lastAlertMessage = null;
let stream=null
let detectionInterval=null
let audioUnlocked = false;

document.addEventListener("click", () => {
    if(!audioUnlocked){
        let sound = document.getElementById("alertSound");
        if(sound){
            sound.play().then(() => {
                sound.pause();
                sound.currentTime = 0;
                audioUnlocked = true;
                console.log("🔊 Audio unlocked");
            }).catch(()=>{});
        }
    }
});

async function startCamera(){

const video=document.getElementById("webcam")

stream=await navigator.mediaDevices.getUserMedia({video:true})

video.srcObject=stream

video.onloadedmetadata=()=>{
video.play()
startDetection()
}

}


function stopCamera(){

if(stream){

stream.getTracks().forEach(track=>track.stop())

}

clearInterval(detectionInterval)

}


function startDetection(){

const video=document.getElementById("webcam")
const canvas=document.getElementById("canvas")
const ctx=canvas.getContext("2d")

detectionInterval=setInterval(async()=>{

canvas.width=video.videoWidth
canvas.height=video.videoHeight

ctx.drawImage(video,0,0)

let frame=canvas.toDataURL("image/jpeg")

let res=await fetch("/detect_frame",{

method:"POST",

headers:{
"Content-Type":"application/json"
},

body:JSON.stringify({image:frame})

})

let data=await res.json()

document.getElementById("processedFrame").src=data.frame

},1000)

}


async function loadStats(){

let res=await fetch("/stats")
let data=await res.json()

document.getElementById("helmetCount").innerText=data.helmet
document.getElementById("vestCount").innerText=data.vest
document.getElementById("totalViolations").innerText=data.helmet+data.vest

}
async function loadAlerts(){

let res = await fetch("/alerts")
let data = await res.json()

let dashboardContainer = document.getElementById("alertsList")
let alertsPageContainer = document.getElementById("alertsPageList")

// clear both
if(dashboardContainer) dashboardContainer.innerHTML = ""
if(alertsPageContainer) alertsPageContainer.innerHTML = ""

// if no alerts
if(data.length === 0){
    if(dashboardContainer) dashboardContainer.innerHTML = "<p>No alerts yet</p>"
    if(alertsPageContainer) alertsPageContainer.innerHTML = "<p>No alerts yet</p>"
    return
}

// ✅ LATEST ALERT for dashboard
let latest = data[data.length - 1]


if(latest && latest.message !== lastAlertMessage){

    let sound = new Audio("/static/sounds/alarm.mp3") // ✅ CORRECT NAME
    sound.play().catch(err => console.log("Sound blocked:", err))

    lastAlertMessage = latest.message
}


console.log("Playing sound")
if(dashboardContainer){
    dashboardContainer.innerHTML = `
    <div class="alert">
        <strong>${latest.message}</strong><br>
        Camera: ${latest.camera}<br>
        Time: ${latest.time}
    </div>
    `
}

// ✅ ALL alerts for alerts page (latest first)
data.slice().reverse().forEach(alert => {
let html = `
<div class="alert">
<strong>${alert.message}</strong><br>
Camera: ${alert.camera}<br>
Time: ${alert.time}
${alert.image ? `<br><img src="${alert.image}" class="alert-img">` : ""}
</div>
`

if(alertsPageContainer){
    alertsPageContainer.innerHTML += html
}

})

}

async function loadAnalytics(){

let res = await fetch("/analytics")
let data = await res.json()
let insights = data.insights

document.getElementById("insight1").innerText =
    "Most frequent violation: " + insights.most_frequent

document.getElementById("insight2").innerText =
    "Peak violation time: " + insights.peak_time

document.getElementById("insight3").innerText =
    "Total violations: " + insights.total
analyticsData = data

// default render
renderSelectedChart()

}
function renderSelectedChart(){

    if(!analyticsData) return

    let type = document.getElementById("chartSelector").value
    let canvas = document.getElementById("analyticsChart")

    if(!canvas) return

    let ctx = canvas.getContext("2d")

    // destroy old chart
    if(analyticsChart){
        analyticsChart.destroy()
    }

    // ✅ MATRIX CHART (custom drawing)
       if(type === "matrix"){

    if(analyticsChart){
        analyticsChart.destroy()
    }

    let helmet = analyticsData.helmet
    let vest = analyticsData.vest

    let data = [
        {x: "Helmet", y: "Violations", v: helmet},
        {x: "Vest", y: "Violations", v: vest}
    ]

    let maxVal = Math.max(helmet, vest, 1)

    analyticsChart = new Chart(ctx, {
        type: 'matrix',
        data: {
            datasets: [{
                label: 'Heatmap',
                data: data,
                backgroundColor: function(ctx) {
                    let value = ctx.dataset.data[ctx.dataIndex].v
                    let alpha = value / maxVal

                    return `rgba(255, 0, 0, ${alpha})` // intensity
                },
                width: () => 100,
                height: () => 100
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                x: {
                    type: 'category',
                    labels: ["Helmet", "Vest"]
                },
                y: {
                    type: 'category',
                    labels: ["Violations"]
                }
            },
            plugins: {
                tooltip: {
                    callbacks: {
                        label: function(ctx){
                            return `${ctx.raw.x}: ${ctx.raw.v}`
                        }
                    }
                }
            }
        }
    })

    return
} 
if(type === "timeline"){

    analyticsChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: analyticsData.times,
            datasets: [
                {
                    label: "Helmet Violations",
                    data: analyticsData.helmet_series,
                    borderWidth: 2,
                    fill: false
                },
                {
                    label: "Vest Violations",
                    data: analyticsData.vest_series,
                    borderWidth: 2,
                    fill: false
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false
        }
    })

    return
}
    // ✅ NORMAL CHARTS
    let chartData = {
        labels: ["Helmet Missing", "Vest Missing"],
        datasets: [{
            label: "Violations",
            data: [analyticsData.helmet, analyticsData.vest]
        }]
    }

    let options = {
        responsive: true,
        maintainAspectRatio: false
    }

    // horizontal bar fix
    if(type === "horizontal"){
        type = "bar"
        options.indexAxis = 'y'
    }

    analyticsChart = new Chart(ctx, {
    type: type,
    data: chartData,
    options: {
        responsive: true,
        maintainAspectRatio: false
    }
})
}



async function loadLogs(){

let res = await fetch("/logs")
let data = await res.json()

let table = document.getElementById("logsTable")
table.innerHTML = ""

data.forEach(log => {

let row = `
<tr>
<td>${new Date(log.timestamp).toLocaleTimeString()}</td>
<td>${log.camera_id}</td>
<td><span class="violation">${log.violation_type}</span></td>
<td>${log.confidence}</td>
</tr>
`

table.innerHTML += row

})

}




async function uploadVideo(){

const fileInput=document.getElementById("videoInput")
const file=fileInput.files[0]

if(!file){

alert("Select video first")
return

}

const formData=new FormData()

formData.append("video",file)

const response=await fetch("/upload",{

method:"POST",
body:formData

})

const result=await response.json()

if(result.video_url){

const player=document.getElementById("videoPlayer")

player.src=result.video_url
player.load()
player.play()

}

}

setInterval(loadLogs,3000)
setInterval(loadStats,2000)
setInterval(loadAlerts,3000)

loadStats()
loadAlerts()
loadLogs()