export default {
	content: ['./central/templates/emails/*.html'],
	corePlugins: {
		backgroundOpacity: false,
		borderOpacity: false,
		divideOpacity: false,
		placeholderOpacity: false,
		ringOpacity: false,
		textOpacity: false,
	},
	theme: {
		extend: {
			spacing: {
				0.5: '2px',
				1: '4px',
				1.5: '6px',
				2: '8px',
				2.5: '10px',
				3: '12px',
				4: '16px',
				5: '20px',
				6: '24px',
				8: '32px',
				10: '40px',
			},
			fontSize: {
				xs: ['12px', '16px'],
				sm: ['14px', '20px'],
				base: ['16px', '24px'],
				lg: ['18px', '28px'],
				xl: ['20px', '28px'],
				'2xl': ['24px', '32px'],
				'3xl': ['30px', '36px'],
			},
			borderRadius: {
				lg: '8px',
				xl: '12px',
			},
		},
	},
}
