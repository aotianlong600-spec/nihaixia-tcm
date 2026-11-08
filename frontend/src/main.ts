import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import './style.css'
import App from './App.vue'
createApp(App).use(ElementPlus).mount('#app')

if(import.meta.env.VITE_BROWSER_APP==='1'&&'serviceWorker' in navigator){
  void navigator.serviceWorker.register(new URL('sw.js',document.baseURI)).catch(error=>{
    console.warn('网页离线资源未能准备',error)
  })
  if(navigator.serviceWorker.controller){
    let refreshing=false
    navigator.serviceWorker.addEventListener('controllerchange',()=>{
      if(refreshing)return
      refreshing=true
      window.location.reload()
    })
  }
}
