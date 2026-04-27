/** 与 data/song-guess-songs.js 保持判题一致，部署时维护双份或自行同步 */
const DEFAULT_MP3 = 'https://file-examples.com/storage/fe68c9e0d978c5e0d8e7e22/2017/11/file_example_MP3_700KB.mp3'
const SONGS = [
  { id: 'sg1', title: '月亮代表我的心', aliases: ['鄧麗君月亮代表我的心'], audioUrl: DEFAULT_MP3 },
  { id: 'sg2', title: '青花瓷', aliases: ['JAY青花瓷'], audioUrl: DEFAULT_MP3 },
  { id: 'sg3', title: '平凡之路', aliases: ['朴树平凡之路'], audioUrl: DEFAULT_MP3 },
  { id: 'sg4', title: '童年', aliases: ['羅大佑童年'], audioUrl: DEFAULT_MP3 },
  { id: 'sg5', title: '海阔天空', aliases: ['beyond海阔天空'], audioUrl: DEFAULT_MP3 },
  { id: 'sg6', title: '但愿人长久', aliases: ['王菲但愿人长久'], audioUrl: DEFAULT_MP3 },
  { id: 'sg7', title: '稻香', aliases: ['周杰倫稻香', '周杰倫 稻香'], audioUrl: DEFAULT_MP3 },
  { id: 'sg8', title: '后来', aliases: ['劉若英后来'], audioUrl: DEFAULT_MP3 }
]
const ID_TO_SONG = {}
SONGS.forEach((s) => {
  ID_TO_SONG[s.id] = s
})
module.exports = { SONGS, ID_TO_SONG }
