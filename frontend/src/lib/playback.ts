export interface PlaybackMedia {src:string;ext:string;}
export type PlaybackFailure = 'unsupported_format' | 'network' | 'decode' | 'unsupported_codec' | 'playback' | 'fullscreen';
