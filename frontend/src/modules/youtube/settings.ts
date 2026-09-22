import component from './Settings.svelte';
import type { SettingsContribution } from '../../lib/settingsTypes';
const contribution:SettingsContribution={
 group:{id:'youtube',label:'YouTube',module:'youtube'},order:4,component,
 sections:[{id:'youtube-downloads',group:'youtube',label:'Downloads',icon:'folder'}],
 searchItems:[{id:'youtube-location',section:'youtube-downloads',label:'Save to location',description:'',keywords:['youtube','download','folder','path','default','custom']}],
};
export default contribution;
