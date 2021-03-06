// PLUGIN: Amara Subtitle (ported from the Subtitle plugin)

(function (Popcorn) {

    var i = 0,
    createDefaultContainer = function(context, id) {

    var ctxContainer = context.container = document.createElement('div'),
        style = ctxContainer.style,
        media = context.media;

        var updatePosition = function() {
            var position = context.position();

            style.fontSize = '16px';
            style.width = media.offsetWidth + 'px';
            style.top = position.top  + media.offsetHeight - ctxContainer.offsetHeight - 63 + 'px';
            style.left = position.left + 'px';

            setTimeout(updatePosition, 10);
        };

        ctxContainer.id = id || Popcorn.guid();
        ctxContainer.className = 'amara-popcorn-subtitles';
        style.position = 'absolute';
        style.color = 'white';
        style.textShadow = 'black 2px 2px 6px';
        style.fontWeight = 'bold';
        style.textAlign = 'center';

        updatePosition();

        context.media.parentNode.appendChild(ctxContainer);

        return ctxContainer;
    };

    /**
     * Subtitle popcorn plug-in
     * Displays a subtitle over the video, or in the target div
     * Options parameter will need a start, and end.
     * Optional parameters are target and text.
     * Start is the time that you want this plug-in to execute
     * End is the time that you want this plug-in to stop executing
     * Target is the id of the document element that the content is
     *  appended to, this target element must exist on the DOM
     * Text is the text of the subtitle you want to display.
     *
     * @param {Object} options
     *
     * Example:
       var p = Popcorn('#video')
           .subtitle({
               start:  5,              // seconds, mandatory
               end:    15,             // seconds, mandatory
               text:   'Hellow world', // optional
               target: 'subtitlediv',  // optional
           })
     **/

Popcorn.plugin('amarasubtitle', {
        _setup: function(options) {
            var newdiv = document.createElement('div');

            newdiv.id = 'subtitle-' + i++;
            newdiv.style.display = 'none';

            // Creates a div for all subtitles to use
            if (!this.container && (!options.target || options.target === 'subtitle-container')) {
                createDefaultContainer(this);
            }

            // if a target is specified, use that
            if (options.target && options.target !== 'subtitle-container') {
                // In case the target doesn't exist in the DOM
                options.container = document.getElementById(options.target) || createDefaultContainer(this, options.target);
            } else {
                // use shared default container
                options.container = this.container;
            }

            if (document.getElementById(options.container.id)) {
                document.getElementById(options.container.id).appendChild(newdiv);
            }
            options.innerContainer = newdiv;

            options.showSubtitle = function() {
                options.innerContainer.innerHTML = options.text || '';
            };
        },
        start: function(event, options){
            options.innerContainer.style.display = 'block';
            options.showSubtitle(options, options.text);
        },
        end: function(event, options) {
            options.innerContainer.style.display = 'none';
            options.innerContainer.innerHTML = '';
        },
        _teardown: function (options) {
            options.container.removeChild(options.innerContainer);
        }
    });
})(Popcorn);
