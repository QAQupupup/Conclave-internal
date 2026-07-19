_CAPTCHA_DETECT_JS = """
() => {
    const url = window.location.href;
    const title = document.title || '';
    const bodyText = (document.body && document.body.innerText) ? document.body.innerText.substring(0, 2000) : '';
    const html = document.documentElement ? document.documentElement.outerHTML.substring(0, 5000) : '';

    const detect = [];

    // 1. Cloudflare 检测
    if (title.includes('Just a moment') || title.includes('Checking your browser') ||
        title.includes('Attention Required') || bodyText.includes('Checking your browser before') ||
        bodyText.includes('cf-browser-verification') || html.includes('cf-challenge') ||
        html.includes('turnstile') || html.includes('grecaptcha')) {
        detect.push('cloudflare');
    }

    // 2. reCAPTCHA 检测
    if (html.includes('google.com/recaptcha') || html.includes('g-recaptcha') ||
        html.includes('recaptcha_challenge') || document.querySelector('iframe[src*="recaptcha"]')) {
        detect.push('recaptcha');
    }

    // 3. hCaptcha 检测
    if (html.includes('hcaptcha.com') || html.includes('h-captcha') ||
        document.querySelector('iframe[src*="hcaptcha"]')) {
        detect.push('hcaptcha');
    }

    // 4. 极验(Geetest)滑块检测
    if (html.includes('gt_') && html.includes('challenge') ||
        html.includes('geetest') || html.includes('nc_1_n1z') ||
        html.includes('gee_') || document.querySelector('.geetest_holder, .gt_slider, [class*="geetest"]')) {
        detect.push('geetest_slider');
    }

    // 5. 腾讯防水墙检测
    if (html.includes('tcaptcha') || html.includes('captcha.qq.com') ||
        document.querySelector('#tcaptcha, iframe[src*="tcaptcha"]')) {
        detect.push('tencent_captcha');
    }

    // 6. Bing 人机验证
    if (url.includes('bing.com') && (
        bodyText.includes('verify you are human') ||
        bodyText.includes('我们需要验证') ||
        bodyText.includes('不是机器人') ||
        bodyText.includes('Help us protect') ||
        html.includes('captcha'))) {
        detect.push('bing_captcha');
    }

    // 7. 通用验证码关键词
    if (bodyText.match(/(captcha|verification|verify.{0,20}human|人机验证|验证码|滑块验证|安全验证)/i)) {
        // 排除误报（如页面正文提到"验证码"这个词但不是验证码页面）
        if (detect.length === 0) {
            // 额外检查：是否有 input 或 canvas 等验证码交互元素
            const hasCaptchaInput = document.querySelector('input[name*="captcha" i], img[src*="captcha" i], canvas[class*="captcha" i]');
            const shortBody = bodyText.length < 500; // 验证码页面通常内容很少
            if (hasCaptchaInput || shortBody) {
                detect.push('generic_captcha');
            }
        }
    }

    // 8. 百度安全验证
    if (url.includes('baidu.com') && (bodyText.includes('安全验证') || html.includes('wappass'))) {
        detect.push('baidu_verify');
    }

    return {
        detected: detect.length > 0,
        types: detect,
        title: title.substring(0, 100),
        url: url,
        body_length: bodyText.length,
    };
}
"""
