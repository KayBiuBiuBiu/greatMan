const { DEFAULT_NICK } = require('../../utils/userProfile')
const { resolveAvatarDisplayUrl } = require('../../utils/avatarResolve')

Component({
  properties: {
    avatarUrl: {
      type: String,
      value: ''
    },
    nickName: {
      type: String,
      value: ''
    },
    letter: {
      type: String,
      value: ''
    },
    size: {
      type: String,
      value: 'md'
    }
  },

  data: {
    showImage: false,
    displayLetter: '?',
    imageSrc: ''
  },

  observers: {
    'avatarUrl, nickName, letter': function () {
      this._syncDisplay()
    }
  },

  lifetimes: {
    attached() {
      this._syncDisplay()
    }
  },

  methods: {
    _syncDisplay() {
      const url = String(this.properties.avatarUrl || '').trim()
      const nick = String(this.properties.nickName || '').trim()
      const letter = String(this.properties.letter || '').trim()
      const displayLetter =
        letter || (nick ? nick.slice(0, 1) : DEFAULT_NICK.slice(0, 1)) || '匿'
      if (!url) {
        this.setData({
          showImage: false,
          imageSrc: '',
          displayLetter
        })
        return
      }
      resolveAvatarDisplayUrl(url)
        .then((src) => {
          if (String(this.properties.avatarUrl || '').trim() !== url) {
            return
          }
          const ok = !!String(src || '').trim()
          this.setData({
            showImage: ok,
            imageSrc: ok ? src : '',
            displayLetter
          })
        })
        .catch(() => {
          this.setData({
            showImage: false,
            imageSrc: '',
            displayLetter
          })
        })
    },

    onImageError() {
      const nick = String(this.properties.nickName || '').trim()
      const letter = String(this.properties.letter || '').trim()
      this.setData({
        showImage: false,
        imageSrc: '',
        displayLetter:
          letter || (nick ? nick.slice(0, 1) : DEFAULT_NICK.slice(0, 1)) || '匿'
      })
    }
  }
})
