async (page) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('tab', { name: '任务', exact: true }).click()
  await page.getByRole('textbox', { name: '消息内容' }).fill('检查窄屏任务布局')
  await page.getByRole('textbox', { name: '消息内容' }).press('Enter')
  await page.getByRole('button', { name: '停止预览' }).waitFor({ state: 'hidden', timeout: 10000 })
  await page.locator('input[type=file]').setInputFiles(Array.from({ length: 5 }, (_, index) => `output/playwright/fixtures/attachment-with-a-long-name-${index}.md`))
  await page.getByRole('textbox', { name: '消息内容' }).fill(Array.from({ length: 15 }, (_, index) => `Line ${index + 1}`).join('\n'))
  await page.setViewportSize({ width: 390, height: 390 })
  const dock = page.locator('.agent-composer-dock')
  const bounds = await dock.boundingBox()
  if (!bounds || bounds.y + bounds.height > 391) throw new Error('Composer dock must stay within short viewport')
  await page.mouse.move(bounds.x + 3, bounds.y + bounds.height / 2)
  await page.mouse.wheel(0, 1000)
  await page.waitForFunction(() => {
    const button = document.querySelector('[aria-label="开始任务"]')
    const rect = button?.getBoundingClientRect()
    return rect && rect.top >= 0 && rect.bottom <= window.innerHeight
  })
  await page.setViewportSize({ width: 320, height: 640 })
  if (await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)) throw new Error('320px horizontal overflow')
  await page.keyboard.press('Control+k')
  console.log('PASS: 5 attachments + 15-line draft at 390x390; send reachable by normal scrolling; no 320px overflow')
}
