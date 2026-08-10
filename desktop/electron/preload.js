const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('reasonix', {
  platform: process.platform,
  version: '0.2.1',
  getProviderSetup: () => ipcRenderer.invoke('provider-setup:status'),
  saveProviderSetup: (setup) => ipcRenderer.invoke('provider-setup:save', setup),
})
